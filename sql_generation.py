# sql_generation.py
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import dateparser
from litellm import acompletion
from backend.config import settings
from cache_and_memory import ConversationManager
from log_stream import log_streamer

logger = logging.getLogger(__name__)

# Dynamically load LLM prompts from dedicated files
PROMPTS_DIR = Path(__file__).parent / "prompts"

def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.error(f"Failed to load prompt file {path}: {e}")
        # Fallback in case of a file read emergency
        return ""

SQL_SYSTEM_PROMPT = load_prompt("sql_system.txt")
EXPLAINER_PROMPT = load_prompt("explainer.txt")

def reload_prompts():
    global SQL_SYSTEM_PROMPT, EXPLAINER_PROMPT
    SQL_SYSTEM_PROMPT = load_prompt("sql_system.txt")
    EXPLAINER_PROMPT = load_prompt("explainer.txt")
    logger.info("AI System Prompts reloaded dynamically from disk.")


# =====================================================================
# 1. NL Filter Parser (formerly nl_filter_parser.py)
# =====================================================================

class NLFilterParser:
    """
    Parses natural language time expressions and filters into SQL WHERE clauses.
    Handles complex temporal queries like "last 3 days", "between Jan and March", etc.
    """
    def __init__(self):
        self.time_patterns = {
            r"last (\d+) (hour|hours|day|days|week|weeks|month|months|year|years)": self._parse_last_n_period,
            r"past (\d+) (hour|hours|day|days|week|weeks|month|months)": self._parse_last_n_period,
            r"today": self._parse_today,
            r"yesterday": self._parse_yesterday,
            r"this (week|month|year)": self._parse_this_period,
            r"last (week|month|year)": self._parse_last_period,
            r"between (.+) and (.+)": self._parse_between,
            r"since (.+)": self._parse_since,
            r"before (.+)": self._parse_before,
            r"after (.+)": self._parse_after,
            r"in (january|february|march|april|may|june|july|august|september|october|november|december)": self._parse_month,
            r"in (\d{4})": self._parse_year,
        }
    
    def parse_temporal_filter(self, query: str, time_column: str = "created_at") -> Optional[str]:
        q_lower = query.lower()
        for pattern, handler in self.time_patterns.items():
            match = re.search(pattern, q_lower)
            if match:
                try:
                    return handler(match, time_column)
                except Exception as e:
                    logger.warning(f"Failed to parse temporal filter '{match.group()}': {e}")
        return None
    
    def _parse_last_n_period(self, match: re.Match, time_column: str) -> str:
        n = int(match.group(1))
        period = match.group(2).rstrip('s')
        return f"{time_column} >= NOW() - INTERVAL '{n} {period}'"
    
    def _parse_today(self, match: re.Match, time_column: str) -> str:
        return f"DATE({time_column}) = CURRENT_DATE"
    
    def _parse_yesterday(self, match: re.Match, time_column: str) -> str:
        return f"DATE({time_column}) = CURRENT_DATE - INTERVAL '1 day'"
    
    def _parse_this_period(self, match: re.Match, time_column: str) -> str:
        period = match.group(1)
        if period == "week":
            return f"{time_column} >= DATE_TRUNC('week', CURRENT_DATE)"
        elif period == "month":
            return f"{time_column} >= DATE_TRUNC('month', CURRENT_DATE)"
        elif period == "year":
            return f"{time_column} >= DATE_TRUNC('year', CURRENT_DATE)"
        return None
    
    def _parse_last_period(self, match: re.Match, time_column: str) -> str:
        period = match.group(1)
        if period == "week":
            return f"{time_column} >= DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '1 week' AND {time_column} < DATE_TRUNC('week', CURRENT_DATE)"
        elif period == "month":
            return f"{time_column} >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AND {time_column} < DATE_TRUNC('month', CURRENT_DATE)"
        elif period == "year":
            return f"{time_column} >= DATE_TRUNC('year', CURRENT_DATE) - INTERVAL '1 year' AND {time_column} < DATE_TRUNC('year', CURRENT_DATE)"
        return None
    
    def _parse_between(self, match: re.Match, time_column: str) -> str:
        start_str = match.group(1).strip()
        end_str = match.group(2).strip()
        start_date = dateparser.parse(start_str)
        end_date = dateparser.parse(end_str)
        if start_date and end_date:
            return f"{time_column} BETWEEN '{start_date.date()}' AND '{end_date.date()}'"
        return None
    
    def _parse_since(self, match: re.Match, time_column: str) -> str:
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        if date_obj:
            return f"{time_column} >= '{date_obj.date()}'"
        return None
    
    def _parse_before(self, match: re.Match, time_column: str) -> str:
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        if date_obj:
            return f"{time_column} < '{date_obj.date()}'"
        return None
    
    def _parse_after(self, match: re.Match, time_column: str) -> str:
        date_str = match.group(1).strip()
        date_obj = dateparser.parse(date_str)
        if date_obj:
            return f"{time_column} > '{date_obj.date()}'"
        return None
    
    def _parse_month(self, match: re.Match, time_column: str) -> str:
        month_name = match.group(1).capitalize()
        month_num = datetime.strptime(month_name, "%B").month
        year = datetime.now().year
        return f"EXTRACT(MONTH FROM {time_column}) = {month_num} AND EXTRACT(YEAR FROM {time_column}) = {year}"
    
    def _parse_year(self, match: re.Match, time_column: str) -> str:
        year = match.group(1)
        return f"EXTRACT(YEAR FROM {time_column}) = {year}"
    
    def parse_comparison_filters(self, query: str, schema: Dict) -> List[str]:
        filters = []
        q_lower = query.lower()
        numeric_columns = []
        for table in schema.get("tables", []):
            for col in table.get("columns", []):
                if any(t in col.get("type", "").lower() for t in ["int", "float", "numeric", "decimal", "real"]):
                    numeric_columns.append(col.get("name"))
        for col in numeric_columns:
            col_lower = col.lower()
            match = re.search(rf"{col_lower}\s*>\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} > {match.group(1)}")
            match = re.search(rf"{col_lower}\s*<\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} < {match.group(1)}")
            match = re.search(rf"{col_lower}\s*=\s*(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} = {match.group(1)}")
            match = re.search(rf"{col_lower}\s+between\s+(\d+\.?\d*)\s+and\s+(\d+\.?\d*)", q_lower)
            if match:
                filters.append(f"{col} BETWEEN {match.group(1)} AND {match.group(2)}")
        return filters
    
    def parse_categorical_filters(self, query: str, schema: Dict) -> List[str]:
        filters = []
        q_lower = query.lower()
        text_columns = []
        for table in schema.get("tables", []):
            for col in table.get("columns", []):
                if any(t in col.get("type", "").lower() for t in ["varchar", "text", "char"]):
                    text_columns.append(col.get("name"))
        for col in text_columns:
            col_lower = col.lower()
            match = re.search(rf"{col_lower}\s*(?:=|is|equals)\s*['\"]?(\w+)['\"]?", q_lower)
            if match:
                value = match.group(1)
                filters.append(f"{col} = '{value}'")
            match = re.search(rf"{col_lower}\s+in\s*\(([^)]+)\)", q_lower)
            if match:
                values = [v.strip().strip("'\"") for v in match.group(1).split(",")]
                values_str = ", ".join([f"'{v}'" for v in values])
                filters.append(f"{col} IN ({values_str})")
        return filters
    
    def build_where_clause(self, query: str, schema: Dict, time_column: str = "created_at") -> str:
        all_filters = []
        temporal = self.parse_temporal_filter(query, time_column)
        if temporal:
            all_filters.append(temporal)
        comparisons = self.parse_comparison_filters(query, schema)
        all_filters.extend(comparisons)
        categorical = self.parse_categorical_filters(query, schema)
        all_filters.extend(categorical)
        if all_filters:
            return "WHERE " + " AND ".join(all_filters)
        return ""


# =====================================================================
# 2. Constraint Aware Query Generator (formerly constraint_aware_query_generator.py)
# =====================================================================

class ConstraintAwareQueryGenerator:
    """Generates SQL queries while respecting user constraints and conversation context"""
    def __init__(self, conversation_manager: ConversationManager):
        self.conversation_manager = conversation_manager
        
    def generate_query(self, user_request: str, schema: Dict, llm_generated_query: str) -> str:
        constraints = self.conversation_manager.get_active_constraints()
        modified_query = llm_generated_query
        if constraints.get("no_joins", False):
            if self._has_join(modified_query):
                logger.warning("LLM query contains JOIN but user requested no joins. Rewriting...")
                modified_query = self._remove_joins(modified_query, constraints, schema)
        target_table = constraints.get("target_table")
        if target_table:
            if not self._uses_table(modified_query, target_table):
                logger.warning(f"LLM query doesn't use target table {target_table}. Rewriting...")
                modified_query = self._rewrite_for_table(modified_query, target_table, constraints, schema)
        if modified_query != llm_generated_query:
            logger.info(f"Query modified to respect constraints:\nOriginal: {llm_generated_query}\nModified: {modified_query}")
        return modified_query
    
    def _has_join(self, query: str) -> bool:
        query_upper = query.upper()
        join_keywords = ["JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "OUTER JOIN", "CROSS JOIN"]
        return any(keyword in query_upper for keyword in join_keywords)
    
    def _uses_table(self, query: str, table_name: str) -> bool:
        query_upper = query.upper()
        table_upper = table_name.upper()
        return table_upper in query_upper
    
    def _remove_joins(self, query: str, constraints: Dict, schema: Dict) -> str:
        target_table = constraints.get("target_table", "oee_details_data")
        operation = constraints.get("operation", "count_distinct")
        target_column = constraints.get("target_column", "machine_id")
        if operation == "count_distinct":
            column_name = self._find_column_name(target_column, target_table, schema)
            return f"SELECT COUNT(DISTINCT {column_name}) FROM {target_table}"
        return f"SELECT * FROM {target_table} LIMIT 100"
    
    def _rewrite_for_table(self, query: str, target_table: str, constraints: Dict, schema: Dict) -> str:
        operation = constraints.get("operation", "count_distinct")
        target_column = constraints.get("target_column", "machine_id")
        if operation == "count_distinct":
            column_name = self._find_column_name(target_column, target_table, schema)
            return f"SELECT COUNT(DISTINCT {column_name}) FROM {target_table}"
        return f"SELECT * FROM {target_table} LIMIT 100"
    
    def _find_column_name(self, target_column: str, table_name: str, schema: Dict) -> str:
        tables = schema.get("tables", [])
        columns = []
        for t in tables:
            if t.get("name") == table_name:
                columns = [c.get("name") for c in t.get("columns", [])]
                break
        if not columns:
            return "id"
        if target_column in columns:
            return target_column
        for col in columns:
            if target_column.lower() in col.lower():
                return col
        common_patterns = ["machine_id", "loop_id", "variant", "grammage", "timestamp", "start_time"]
        for pat in common_patterns:
            if pat in columns:
                return pat
        if "id" in columns:
            return "id"
        return columns[0] if columns else "id"
    
    def build_context_prompt(self, user_request: str, schema: Dict) -> str:
        context = self.conversation_manager.get_conversation_context(last_n=5)
        constraints = self.conversation_manager.get_active_constraints()
        rules = []
        if constraints.get("no_joins", False):
            rules.append("- DO NOT USE ANY JOIN OPERATIONS")
            rules.append("- Query must use only a single table")
        if constraints.get("target_table"):
            rules.append(f"- Query MUST use table: {constraints['target_table']}")
        if constraints.get("operation") == "count_distinct":
            rules.append("- Use COUNT(DISTINCT column_name) for counting unique values")
        rules_str = "\n".join(rules) if rules else "No active strict constraints."
        try:
            prompt_path = Path(__file__).parent / "prompts" / "constraint_generator.txt"
            template = prompt_path.read_text(encoding="utf-8")
            return template.format(
                context=context,
                constraint_rules=rules_str,
                user_request=user_request
            )
        except Exception as e:
            logger.error(f"Failed to load constraint_generator prompt: {e}")
            return f"Generate SQL for {user_request}. Constraints: {rules_str}"


# =====================================================================
# 3. SQL Generator (formerly sql_generator.py)
# =====================================================================

class SQLGenerator:
    def __init__(self, db_connector):
        self.db = db_connector
        from search_and_rag import PromptRAG
        self.prompt_rag = PromptRAG()
        self.prompt_rag.index_prompts(
            rules_dir="./prompts/rules",
            examples_dir="./prompts/examples"
        )


    def sanitize_single_table_query(self, sql: str) -> str:
        # Strip notes and conversational fluff at the end of the query
        clean_lines = []
        for line in sql.splitlines():
            line_strip = line.strip()
            if not line_strip:
                continue
            if line_strip.lower().startswith(("note:", "explanation:", "here is", "corrected", "i corrected", "this sql", "sql:", "output:", "please note", "hope this", "let me know")):
                break
            clean_lines.append(line)
        sql = "\n".join(clean_lines).strip()

        sql = re.sub(r"```.*", "", sql, flags=re.DOTALL).strip()
        if ";" in sql:
            for part in sql.split(";"):
                if "select" in part.lower():
                    sql = part.strip()
                    break
        sql = sql.strip().rstrip(";")

        group_by_match = re.search(r"GROUP\s+BY\s+(.*?)(?:ORDER|LIMIT|$)", sql, flags=re.IGNORECASE)
        if group_by_match:
            gb_cols = [c.strip() for c in group_by_match.group(1).split(',')]
            select_match = re.search(r"^SELECT\s+(.*?)FROM", sql, flags=re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1)
                missing_cols = []
                for col in gb_cols:
                    clean_col = col.split()[0]
                    if not re.search(rf"\b{re.escape(clean_col)}\b", select_clause, flags=re.IGNORECASE):
                        missing_cols.append(clean_col)
                if missing_cols:
                    new_select = "SELECT " + ", ".join(missing_cols) + ", "
                    sql = re.sub(r"^SELECT\s+", new_select, sql, flags=re.IGNORECASE)

        if "wastage_records" in sql.lower():
            sql = re.sub(r"\bstart_time\b", "production_start_time", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*1['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*2['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*3['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*1%['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*2%['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*3%['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Morning Shift|Morning)['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Afternoon Shift|Afternoon)['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Night Shift|Night)['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)

        sql_upper = sql.upper()
        join_keywords = ["JOIN", "INNER", "LEFT", "RIGHT", "CROSS", "OUTER"]
        if any(re.search(rf"\b{kw}\b", sql_upper) for kw in join_keywords):
            return sql
            
        if "," in sql:
            from_idx = sql_upper.find("FROM")
            if from_idx != -1:
                where_idx = sql_upper.find("WHERE", from_idx)
                sub_from_to_where = sql[from_idx:where_idx] if where_idx != -1 else sql[from_idx:]
                if "," in sub_from_to_where:
                    return sql

        from_pattern = r"\bFROM\s+([a-zA-Z0-9_]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?"
        from_match = re.search(from_pattern, sql, flags=re.IGNORECASE)
        if not from_match:
            return sql
            
        table_name = from_match.group(1)
        alias = from_match.group(2)
        if alias and alias.upper() in ["WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "ON", "JOIN", "INNER", "LEFT", "RIGHT"]:
            alias = None
        if alias:
            pattern = rf"\bFROM\s+{table_name}\s+(?:AS\s+)?{alias}\b"
            sql = re.sub(pattern, f"FROM {table_name}", sql, flags=re.IGNORECASE)
            sql = re.sub(rf"\b{alias}\.", "", sql, flags=re.IGNORECASE)
        sql = re.sub(rf"\b{table_name}\.", "", sql, flags=re.IGNORECASE)
        return sql

    def _format_schema(self, schema_info: dict) -> str:
        lines = []
        for table in schema_info.get("tables", []):
            row_count = table.get("row_count", 0)
            status = f"({row_count:,} rows)" if row_count > 0 else "(0 rows - EMPTY)"
            lines.append(f"Table: {table['name']} {status}")
            cols = [f"{c['name']} ({c['type']})" for c in table.get("columns", [])]
            lines.append("  Columns: " + ", ".join(cols))
            if table.get("samples"):
                lines.append(f"  Sample row: {table['samples'][0]}")
        return "\n".join(lines)
    
    async def generate_sql(self, query: str, schema_info: dict, domain_hints: str, max_retries: int = 1, matched_tables: list = None) -> str:
        # Retrieve dynamically matching rules and examples from PromptRAG
        try:
            rules_str, examples_str = self.prompt_rag.get_relevant_prompt_context(query)
            if rules_str:
                domain_hints = f"{domain_hints}\n\n═══════════════════════════════════════════════════\nSEMANtICALLY RELEVANT RULES:\n═══════════════════════════════════════════════════\n{rules_str}"
            if examples_str:
                domain_hints = f"{domain_hints}\n\n═══════════════════════════════════════════════════\nSEMANtICALLY RELEVANT EXAMPLES:\n═══════════════════════════════════════════════════\n{examples_str}"
        except Exception as e:
            logger.error(f"Failed to query PromptRAG: {e}")

        if matched_tables:
            domain_hints = f"{domain_hints}\n\nCONFIRMED RELEVANT TABLES TO USE: {', '.join(matched_tables)}"
        schema_text = self._format_schema(schema_info)
        prompt = SQL_SYSTEM_PROMPT.format(schema_text=schema_text, domain_hints=domain_hints)
        
        print("\n" + "=" * 60)
        print("💡 [FORMULA & DOMAIN HINTS REACHING LLM] 💡")
        print(domain_hints)
        print("-" * 60)
        print("🔥 [FULL SQL GENERATOR SYSTEM PROMPT] 🔥")
        print(prompt)
        print("=" * 60 + "\n")
        
        logger.info(f"Domain hints reaching LLM:\n{domain_hints}")
        logger.info(f"Generating SQL for query: '{query}'")
        logger.info(f"Full System Prompt sent to LLM:\n{prompt}")
        
        last_error = None
        last_sql = None
        
        for attempt in range(max_retries + 1):
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": query}
            ]
            
            if last_error and last_sql:
                import re as _re
                err_lower = last_error.lower()
                if "undefinedcolumn" in err_lower or ("column" in err_lower and "does not exist" in err_lower):
                    col_match = _re.search(r'column ["\']?(\S+?)["\']? does not exist', last_error, _re.IGNORECASE)
                    bad_col = col_match.group(1) if col_match else "unknown"
                    correction_hint = (
                        f"ERROR TYPE: UndefinedColumn — column '{bad_col}' does not exist.\n"
                        f"FIX: Check the DATABASE SCHEMA. Common mistakes:\n"
                        f"- oee_details_data has NO plant_id or line_id column.\n"
                        f"- No 'oee' column exists — use downtime_mins, good_bags, failed_bags.\n"
                        f"- Time column for OEE/EGA is 'start_time', for wastage is 'production_start_time'.\n"
                        f"- Do NOT join oee_details_data to gmiiot_plants (impossible join)."
                    )
                elif "undefinedfunction" in err_lower or "operator does not exist" in err_lower:
                    correction_hint = (
                        f"ERROR TYPE: TypeMismatch — you joined or compared columns of incompatible types.\n"
                        f"FIX: plant_id on gmiiot_plants is INTEGER. "
                        f"Use ILIKE for text matching. Check JOIN column types match."
                    )
                elif "syntax" in err_lower:
                    correction_hint = (
                        f"ERROR TYPE: SyntaxError.\n"
                        f"FIX: Check for missing FROM clause, unmatched parentheses, "
                        f"missing quotes around string values, or invalid GROUP BY."
                    )
                elif "undefinedtable" in err_lower or ("relation" in err_lower and "does not exist" in err_lower):
                    tbl_match = _re.search(r'relation ["\']?(\S+?)["\']? does not exist', last_error, _re.IGNORECASE)
                    bad_tbl = tbl_match.group(1) if tbl_match else "unknown"
                    correction_hint = (
                        f"ERROR TYPE: UndefinedTable — table '{bad_tbl}' does not exist.\n"
                        f"FIX: Only use tables listed in the DATABASE SCHEMA above."
                    )
                else:
                    correction_hint = f"ERROR: {last_error[:300]}"

                messages.append({"role": "assistant", "content": last_sql})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous SQL failed. Diagnosis:\n\n{correction_hint}\n\n"
                        f"BROKEN SQL:\n{last_sql}\n\n"
                        f"Write the corrected SQL. Return ONLY the SQL starting with SELECT."
                    )
                })
                logger.info(f"Retry {attempt} — self-healing with classified error: {correction_hint[:80]}")
            
            try:
                log_msg = f"\n🚀 [SENDING TO LLM: SQL GENERATION - ATTEMPT {attempt + 1}] 🚀\n{json.dumps(messages, indent=2)}\n" + "=" * 60 + "\n"
                print(log_msg)
                await log_streamer.broadcast(log_msg)

                response = await acompletion(
                    model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                    messages=messages,
                    api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                    temperature=0.0,
                    timeout=300
                )
                sql = response.choices[0].message.content.strip()

                log_msg = f"\n✅ [RECEIVED FROM LLM: SQL GENERATION - ATTEMPT {attempt + 1}] ✅\n{sql}\n" + "=" * 60 + "\n"
                print(log_msg)
                await log_streamer.broadcast(log_msg)
                
                sql_blocks = re.findall(r"```sql\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                if not sql_blocks:
                    sql_blocks = re.findall(r"```\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                
                if sql_blocks:
                    sql = sql_blocks[-1].strip()
                else:
                    last_start = -1
                    marker_len = 0
                    for marker in ["```sql", "```SQL", "```"]:
                        idx = sql.rfind(marker)
                        if idx > last_start:
                            last_start = idx
                            marker_len = len(marker)
                    
                    if last_start != -1:
                        sql = sql[last_start + marker_len:].strip()
                        sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                    else:
                        select_match = re.search(r"\bSELECT\b", sql, flags=re.IGNORECASE)
                        if select_match:
                            sql = sql[select_match.start():].strip()
                        else:
                            sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"^```\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                
                sql = sql.strip().rstrip(";")
                sql = self.sanitize_single_table_query(sql)
                
                try:
                    await self.db.execute_query(f"EXPLAIN {sql}")
                    logger.info(f"Generated and validated SQL: {sql}")
                    return sql
                except Exception as validation_error:
                    last_error = str(validation_error)
                    last_sql = sql
                    error_msg = str(validation_error)
                    if "column" in error_msg.lower() and "does not exist" in error_msg.lower():
                        error_msg += "\n\nTROUBLESHOOTING: Check if column name exists in schema. Common mistakes:\n"
                        error_msg += "- Using 'machine_name' instead of 'machine_id'\n"
                        error_msg += "- Missing 'g' suffix in grammage values (e.g., grammage = '10.5g' not grammage = 10.5)"
                    elif "syntax" in error_msg.lower():
                        error_msg += "\n\nTROUBLESHOOTING: Check SQL syntax. Common issues:\n"
                        error_msg += "- Missing quotes around string values (e.g., variant = 'Ridge Cut')\n"
                        error_msg += "- Incorrect WHERE clause structure"
                    
                    logger.warning(f"SQL validation failed (attempt {attempt + 1}): {error_msg}")
                    last_error = error_msg
                    if attempt == max_retries:
                        raise Exception(error_msg)
                    
            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"SQL Generation failed after {max_retries + 1} attempts: {e}")
                    raise e
                last_error = str(e)
        
        raise Exception(f"SQL generation failed after {max_retries + 1} attempts")

    async def explain_results(self, query: str, sql: str, results: dict, extra_context: str = "") -> str:
        try:
            sample_results = json.dumps(results.get("rows", [])[:20], indent=2)
        except Exception as e:
            logger.error(f"Error serializing results: {e}")
            sample_results = str(results.get("rows", []))
        
        row_count = results.get("row_count", 0)
        is_count_query = False
        if row_count == 1 and results.get("rows"):
            try:
                row_data = results["rows"][0]
                if isinstance(row_data, dict) and len(row_data) == 1:
                    key = list(row_data.keys())[0]
                    if key.lower() in ["count", "total", "count(*)"]:
                        is_count_query = True
            except Exception:
                pass
        
        empty_result_guidance = ""
        if row_count == 0 or (is_count_query and results.get("rows") and len(results["rows"]) > 0):
            try:
                if is_count_query:
                    count_value = list(results["rows"][0].values())[0]
                    if count_value == 0:
                        empty_result_guidance = """\n\nIMPORTANT: The result is empty or zero. You MUST:
1. Clearly state what was found (or not found)
2. Provide 2-3 possible reasons why this might be the case (e.g., date not in database, no matching variant, machine not recorded)
3. Suggest checking available dates or alternative filters
4. Ask helpful follow-up questions to guide the user

Example format:
"Based on the query results, there are 0 [items] matching your criteria. This could mean:
- The date you specified may not have data in the database
- The variant or machine ID might not match exactly
- Data for that period hasn't been recorded yet

To investigate further, you might want to:
- Check what dates are available in the database
- Verify the exact variant names or machine IDs
- Try a broader date range

Would you like me to show you available dates or machines?"
"""
                else:
                    empty_result_guidance = """\n\nIMPORTANT: No rows were returned. You MUST:
1. Clearly state that no matching records were found
2. Suggest 2-3 possible reasons (date mismatch, variant name mismatch, no data for that period)
3. Offer to check available dates, variants, or machines
4. Be helpful and proactive in guiding the user"""
            except Exception:
                pass
        
        prompt = EXPLAINER_PROMPT.format(
            query=query,
            sql=sql,
            columns=results.get("columns", []),
            row_count=row_count,
            sample_results=sample_results
        ) + empty_result_guidance
        
        if extra_context:
            prompt = f"ADDITIONAL CONTEXT FROM RAG DOCUMENTS:\n{extra_context}\n\n---\n\n{prompt}"
        
        logger.info(f"Explaining results for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: EXPLAIN RESULTS] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            explanation = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: EXPLAIN RESULTS] ✅\n{explanation}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            return explanation
        except Exception as e:
            logger.error(f"Explanation generation failed: {e}")
            raise e

    async def explain_rag_concept(self, query: str, rag_context: str) -> str:
        """
        Explain a conceptual manufacturing question directly using RAG reference documents.
        """
        fallback_rag_prompt_template = load_prompt("fallback_rag.txt")
        prompt = fallback_rag_prompt_template.format(
            query=query, 
            rag_context=rag_context if rag_context else 'No reference material found.'
        )
        logger.info(f"Explaining RAG concept for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: RAG CONCEPT EXPLANATION] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            response_content = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: RAG CONCEPT EXPLANATION] ✅\n{response_content}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            return response_content
        except Exception as e:
            logger.error(f"RAG Explanation generation failed: {e}")
            raise e

    async def explain_error_conversational(self, query: str, error_msg: str, stage: str) -> str:
        """
        Explain a SQL generator or database execution error to the user in a friendly,
        plain-English way, and ask a clarifying question so the user can understand and help us fix it.
        """
        fallback_error_prompt_template = load_prompt("fallback_error.txt")
        prompt = fallback_error_prompt_template.format(
            query=query,
            stage=stage,
            error_msg=error_msg
        )
        logger.info(f"Explaining database error conversationally for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: ERROR CONVERSATIONAL EXPLANATION] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            response_content = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: ERROR CONVERSATIONAL EXPLANATION] ✅\n{response_content}\n" + "=" * 60 + "\n"
            print(log_msg)
            await log_streamer.broadcast(log_msg)

            return response_content
        except Exception as e:
            logger.error(f"Error explanation generation failed: {e}")
            raise e

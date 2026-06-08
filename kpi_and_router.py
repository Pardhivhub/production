"""
KPI Engine, Router & Suggester - Manages manufacturing formulas, query classification, intent routing, and follow-up suggestions
"""
import logging
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from difflib import get_close_matches

logger = logging.getLogger(__name__)

TIME_COLUMN_MAP = {
    "oee_details_data": "start_time",
    "ega_details_data": "start_time",
    "production_speed_details_data": "start_time",
    "wastage_records": "production_start_time",
    "gsm_usage_details": "date",
}

FORMULAS_CATALOG = {
  "OEE": {
    "metric": "OEE_Availability",
    "aliases": ["oee", "oee performance", "machine performance", "overall equipment effectiveness", "overall efficiency", "equipment efficiency", "availability"],
    "type": "derived_kpi",
    "table": "oee_details_data",
    "formula": "((60.0 - SUM(downtime_mins)) / 60.0) * 100 per machine per hour",
    "query": "SELECT machine_id, machine_name, SUM(downtime_mins) AS total_downtime, ROUND(((COUNT(*)*60.0 - SUM(downtime_mins))/(COUNT(*)*60.0))*100::numeric, 2) AS availability_pct FROM oee_details_data GROUP BY machine_id, machine_name ORDER BY availability_pct DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"],
    "notes": "There is NO 'oee' column! Use downtime_mins for downtime and availability. good_bags and failed_bags for quality."
  },
  "EGA_percent": {
    "metric": "EGA_percent",
    "aliases": ["ega", "ega percent", "ega %", "ega_percentage", "excess give away percent", "extra give away percent", "excess give away %", "extra weight given away", "excess give away", "giveaway", "extra weight"],
    "type": "stored_kpi",
    "table": "ega_details_data",
    "formula": "AVG(ega_percent)",
    "query": "SELECT machine_id, machine_name, AVG(ega_percent) AS avg_ega FROM ega_details_data GROUP BY machine_id, machine_name ORDER BY avg_ega DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant", "grammage"],
    "notes": "ega_percent is a stored NUMERIC column per hourly row. Use AVG(ega_percent) when grouping by machine. grammage is NUMERIC like 10.5, 20, 43 without 'g' suffix."
  },
  "Wastage": {
    "metric": "Wastage",
    "aliases": ["wastage", "waste", "scrap", "material loss", "wastage kg"],
    "type": "stored_kpi",
    "table": "wastage_records",
    "formula": "SUM(wastage_kg)",
    "query": "SELECT machine_id, line_id, SUM(wastage_kg) AS total_wastage FROM wastage_records GROUP BY machine_id, line_id",
    "time_column": "production_start_time",
    "groupable_by": ["machine_id", "line_id", "shift", "grammage"],
    "filters": ["machine_id", "line_id", "shift"]
  },
  "Production_Speed": {
    "metric": "Production_Speed",
    "aliases": ["production speed", "speed", "actual speed", "machine speed", "avg speed", "bpm"],
    "type": "stored_kpi",
    "table": "production_speed_details_data",
    "formula": "AVG(unnest(production_speed_bpm))",
    "query": "SELECT machine_id, machine_name, ROUND(AVG(unnest_speed)::numeric,2) AS avg_speed_bpm FROM production_speed_details_data, unnest(production_speed_bpm) AS unnest_speed GROUP BY machine_id, machine_name ORDER BY avg_speed_bpm DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"],
    "notes": "production_speed_bpm is a NUMERIC ARRAY column. Use unnest(production_speed_bpm) to aggregate it. Do NOT use production_speed (it is a JSON text column)."
  }
}

RELATIONSHIPS_CATALOG = [
  {
    "from_table": "ega_details_data",
    "from_column": "machine_id",
    "to_table": "oee_details_data",
    "to_column": "machine_id",
    "type": "many-to-many",
    "description": "Link machine production data (EGA) with OEE metrics via machine_id"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "loop_id",
    "to_table": "oee_details_data",
    "to_column": "loop_id",
    "type": "many-to-many",
    "description": "Link production loops across EGA and OEE tables"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "grammage",
    "to_table": "oee_details_data",
    "to_column": "grammage",
    "type": "many-to-many",
    "description": "Link by SKU/grammage"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "variant",
    "to_table": "oee_details_data",
    "to_column": "variant",
    "type": "many-to-many",
    "description": "Link product variant data between EGA and OEE"
  },
  {
    "from_table": "wastage_records",
    "from_column": "machine_id",
    "to_table": "ega_details_data",
    "to_column": "machine_id",
    "type": "many-to-many",
    "description": "Link wastage records to machine production data"
  },
  {
    "from_table": "wastage_records",
    "from_column": "line_id",
    "to_table": "ega_details_data",
    "to_column": "loop_id",
    "type": "many-to-many",
    "description": "Link production loop/line for wastage reporting"
  },
  {
    "from_table": "wastage_records",
    "from_column": "grammage",
    "to_table": "ega_details_data",
    "to_column": "grammage",
    "type": "many-to-many",
    "description": "Link wastage records to SKU/grammage of production"
  }
]

SHIFT_PATTERNS = {
  "morning shift": {
    "start": "06:00:00",
    "end": "14:00:00",
    "label": "Morning Shift",
    "aliases": ["morning", "morning shift", "shift 1", "first shift", "day shift"]
  },
  "afternoon shift": {
    "start": "14:00:00",
    "end": "22:00:00",
    "label": "Afternoon Shift",
    "aliases": ["afternoon", "afternoon shift", "shift 2", "second shift", "evening shift"]
  },
  "night shift": {
    "start": "22:00:00",
    "end": "06:00:00",
    "label": "Night Shift",
    "aliases": ["night", "night shift", "shift 3", "third shift", "overnight shift"]
  }
}


class KPIEngine:
    def __init__(self, schema_info: dict = None):
        self.schema_info = schema_info or {"tables": []}
        
        try:
            path = Path(__file__).parent / "config" / "kpi_catalog.json"
            with open(path, encoding="utf-8") as f:
                catalog = json.load(f)
            self.kpi_formulas = catalog.get("formulas", FORMULAS_CATALOG)
            self.relationships = catalog.get("relationships", RELATIONSHIPS_CATALOG)
            self.shift_patterns = catalog.get("shifts", SHIFT_PATTERNS)
        except Exception:
            self.kpi_formulas = FORMULAS_CATALOG
            self.relationships = RELATIONSHIPS_CATALOG
            self.shift_patterns = SHIFT_PATTERNS

    def compile_domain_hints(self, user_query: str) -> dict:
        q_lower = user_query.lower()
        hints = []
        corrections = {}
        matched_tables = set()

        # ── Machine synonym resolution ──────────────────────────────────
        machine_num_patterns = re.findall(
            r'(?:machine[\s\-]*(\d+)|weigher[\s\-]*(\d+)|machine\s*id[\s\-]*(\d+))',
            q_lower
        )
        machine_ids_mentioned = []
        for groups in machine_num_patterns:
            mid = next((g for g in groups if g), None)
            if mid:
                machine_ids_mentioned.append(int(mid))
        
        if machine_ids_mentioned:
            if len(machine_ids_mentioned) == 1:
                hints.append(
                    f"- MACHINE FILTER: User refers to machine #{machine_ids_mentioned[0]}. "
                    f"Use: machine_id = {machine_ids_mentioned[0]}"
                )
            else:
                ids_str = ", ".join(str(m) for m in machine_ids_mentioned)
                in_clause = ", ".join(str(m) for m in machine_ids_mentioned)
                hints.append(
                    f"- COMPARE MACHINES RULE: User wants to compare machines {ids_str} side by side. "
                    f"MANDATORY: Use machine_id IN ({in_clause}) WITH GROUP BY machine_id, machine_name. "
                    f"Include machine_id AND machine_name in SELECT. "
                    f"Result MUST have {len(machine_ids_mentioned)} rows — one per machine. "
                    f"NEVER omit GROUP BY and return a single combined total row."
                )
        
        compare_keywords = ["compare", " vs ", " vs.", " versus ", " and machine ", " and weigher "]
        if any(kw in q_lower for kw in compare_keywords) and len(machine_ids_mentioned) >= 2:
            hints.append(
                "- COMPARISON INTENT DETECTED: User is comparing multiple machines. "
                "Each machine MUST be its own row. Always add GROUP BY machine_id, machine_name. "
                "Do NOT aggregate all machines into a single total row."
            )

        # ── Table routing by keyword ────────────────────────────────────
        if any(w in q_lower for w in ["ega", "giveaway", "give away", "excess give away", "extra weight"]):
            matched_tables.add("ega_details_data")
        if any(w in q_lower for w in ["oee", "downtime", "availability", "performance", "quality", "good bags", "failed bags"]):
            matched_tables.add("oee_details_data")
        if any(w in q_lower for w in ["speed", "bpm", "production speed"]):
            matched_tables.add("production_speed_details_data")
        if any(w in q_lower for w in ["wastage", "waste", "scrap"]):
            matched_tables.add("wastage_records")

        # 1. Math aggregate and catalog metric detection
        for kpi_id, meta in self.kpi_formulas.items():
            aliases = meta.get("aliases", [kpi_id.replace("_", " ").lower()])
            if any(alias in q_lower for alias in aliases):
                metric = meta.get("metric")
                table = meta.get("table")
                formula = meta.get("formula")
                query_example = meta.get("query")
                notes = meta.get("notes", "")
                
                hint_text = (
                    f"- KPI METRIC DETECTED ({metric.upper()}): Use table '{table}', "
                    f"aggregate with formula: `{formula}`. "
                    f"Example: `{query_example}`"
                )
                if notes:
                    hint_text += f" NOTE: {notes}"
                hints.append(hint_text)
                if table:
                    matched_tables.add(table.split(".")[-1])

        # 2. Shift Range Processing
        for shift_name, shift_data in self.shift_patterns.items():
            start_t = shift_data["start"]
            end_t = shift_data["end"]
            label = shift_data["label"]
            aliases = shift_data.get("aliases", [shift_name])
            if any(alias in q_lower for alias in aliases):
                time_col = "start_time"
                for t in matched_tables:
                    if t in TIME_COLUMN_MAP:
                        time_col = TIME_COLUMN_MAP[t]
                        break

                if label == "Night Shift":
                    time_filter = (
                        f"({time_col}::time >= '{start_t}' "
                        f"OR {time_col}::time < '{end_t}')"
                    )
                else:
                    time_filter = (
                        f"{time_col}::time >= '{start_t}' "
                        f"AND {time_col}::time < '{end_t}'"
                    )

                hints.append(
                    f"- SHIFT FILTER ({label.upper()}): "
                    f"Do NOT join shift_assignments. "
                    f"Filter directly: WHERE {time_filter}"
                )

        # 3. Fuzzy Spelling & Column/Table Correction
        actual_columns = []
        column_to_table = {}
        for table_meta in self.schema_info.get("tables", []):
            table_name = table_meta.get("name", "")
            for col in table_meta.get("columns", []):
                col_name = col.get("name", "")
                actual_columns.append(col_name)
                column_to_table[col_name] = table_name

        EXCLUDE_FUZZY = {
            "find", "show", "list", "get", "each", "what", "where", "when", "with", "have",
            "mean", "name", "date", "time", "hour", "year", "month", "week", "day", "rate",
            "cost", "peak", "free", "data", "line", "type", "from", "info", "than", "alert"
        }

        words = re.findall(r"\b\w+\b", q_lower)
        for word in words:
            if len(word) < 4 or word in EXCLUDE_FUZZY:
                continue
            if any(word in col for col in actual_columns):
                continue
                
            matches = get_close_matches(word, actual_columns, n=1, cutoff=0.80)
            if matches and matches[0] != word:
                matched_col = matches[0]
                corrections[word] = matched_col
                target_tbl = column_to_table[matched_col]
                matched_tables.add(target_tbl)
                hints.append(
                    f"- FUZZY MATCH: The word '{word}' was mapped to the database column '{matched_col}' "
                    f"in table '{target_tbl}'."
                )

        # 4. Multi-Table Join Generation
        if len(matched_tables) > 1:
            for rel in self.relationships:
                from_t = rel["from_table"].split(".")[-1]
                to_t = rel["to_table"].split(".")[-1]
                if from_t in matched_tables and to_t in matched_tables:
                    hints.append(
                        f"- JOIN RELATIONSHIP DETECTED: To join '{from_t}' and '{to_t}', "
                        f"use: `JOIN {to_t} ON {from_t}.{rel['from_column']} = {to_t}.{rel['to_column']}` "
                        f"({rel['description']})."
                    )

        # 5. Counting and Filtering Rules
        counting_keywords = ["how many", "count", "total number", "number of"]
        listing_keywords = ["list all", "show all", "give me all", "display all", "get all"]
        filtering_keywords = ["where", "with", "having", ">", "<", "=", "above", "below", "greater", "less", "highest", "lowest", "maximum", "minimum", "best", "worst"]
        
        has_counting = any(kw in q_lower for kw in counting_keywords)
        has_listing = any(kw in q_lower for kw in listing_keywords)
        has_filtering = any(kw in q_lower for kw in filtering_keywords)
        
        if has_counting or has_listing:
            if has_filtering:
                hints.append(
                    "- COUNTING + FILTERING RULE: User wants both count AND details. "
                    "Return ALL matching rows with SELECT * or SELECT [columns] WHERE [condition]. "
                    "Do NOT use LIMIT. The explainer will count and list all items."
                )
            elif "only" in q_lower or "just" in q_lower:
                hints.append(
                    "- COUNT-ONLY RULE: User wants only the count. Use SELECT COUNT(*) or COUNT(DISTINCT column)."
                )
            else:
                hints.append(
                    "- TOTAL COUNT RULE: User wants to count all items. "
                    "Return ALL rows with SELECT * FROM table. The explainer will count and report the total."
                )
        
        if has_listing and has_filtering:
            hints.append(
                "- LISTING RULE: Return ALL matching rows without LIMIT. "
                "Include relevant columns for context (IDs, names, metrics). "
                "The explainer will state: 'There are X items with [condition]' and list all of them."
            )

        if has_filtering:
            hints.append(
                "- FILTERING/COMPARISON RULE: The user is asking to filter or find records matching a specific comparison "
                "(e.g., 'highest', 'lowest', 'greater than', 'above', 'below', '<', '>', '=', etc.). "
                "For 'highest' or 'lowest' queries, use ORDER BY with the metric column and LIMIT 1. "
                "For threshold comparisons, list the individual records/rows matching the filter condition, "
                "including relevant identifying columns (like machine_id, loop_id, variant, start_time/timestamp) "
                "and the metric column itself. Do NOT aggregate with AVG() or SUM() for the whole table when filtering. "
                "Example for 'highest ega': `SELECT machine_id, loop_id, variant, start_time, ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 AS ega_percent FROM ega_details_data ORDER BY ega_percent DESC LIMIT 1` "
                "Example for 'ega greater than 2.5': `SELECT machine_id, loop_id, variant, start_time, ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 AS ega_percent FROM ega_details_data WHERE ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 > 2.5`"
            )

        # 6. Date/Time parsing for specific dates
        date_patterns = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', user_query)
        if date_patterns:
            time_col = "start_time"
            for t in matched_tables:
                if t in TIME_COLUMN_MAP:
                    time_col = TIME_COLUMN_MAP[t]
                    break
            
            for date_str in date_patterns:
                hints.append(
                    f"- PARSED TIME FILTER: {time_col}::date = '{date_str}'"
                )
                hints.append(
                    f"- DATE+GROUPBY RULE: Since a date filter is applied, ALWAYS use "
                    f"GROUP BY machine_id (and machine_name if selected) so each machine "
                    f"shows its daily aggregate, not just one hourly row."
                )
                break

        # 7. Grammage format normalization
        grammage_patterns = re.findall(r'\b(\d+(?:\.\d+)?)\s*(?:g\b|grams?\b|(?=\s+(?:ridge|flat|variant)))', q_lower, re.IGNORECASE)
        seen_grammage = set()
        for gram_val in grammage_patterns:
            try:
                gram_num = float(gram_val)
                if gram_num > 5 and gram_num < 500 and gram_num not in seen_grammage:
                    seen_grammage.add(gram_num)
                    hints.append(
                        f"- GRAMMAGE FORMAT: User mentioned '{gram_val}' grams. "
                        f"The grammage column is NUMERIC (stores numbers like 10.5, 20, 43, 85, 90, NOT text). "
                        f"Use: grammage = {gram_num} (as a NUMBER without quotes or 'g' suffix)"
                    )
                    break
            except ValueError:
                continue

        # 8. Availability semantic mapping
        if "availability" in q_lower or "available" in q_lower:
            if any(pattern in q_lower for pattern in ["100%", "100 percent", "full availability", "perfect availability", "maximum availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 100% availability. "
                    "This means ZERO downtime. Use: WHERE downtime_mins = 0 "
                )
            elif any(pattern in q_lower for pattern in ["0%", "zero percent", "no availability", "lowest availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 0% availability. "
                    "This means MAXIMUM downtime. Use: ORDER BY downtime_mins DESC "
                )
            elif "highest availability" in q_lower or "best availability" in q_lower or "most available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for highest availability. "
                    "This means LOWEST downtime. Use: ORDER BY downtime_mins ASC LIMIT 1 "
                )
            elif "lowest availability" in q_lower or "worst availability" in q_lower or "least available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for lowest availability. "
                    "This means HIGHEST downtime. Use: ORDER BY downtime_mins DESC LIMIT 1 "
                )
            else:
                hints.append(
                    "- AVAILABILITY CALCULATION: The 'availability' column does not exist. "
                    "Calculate it as: ((60.0 - downtime_mins) / 60.0) * 100 "
                    "(assuming 60-minute intervals). Use downtime_mins column from oee_details_data."
                )

        return {
            "hints": "\n".join(hints) if hints else "No specific manufacturing templates detected.",
            "corrections": corrections,
            "matched_tables": list(matched_tables)
        }


class QueryRouter:
    def __init__(self, schema: dict = None):
        self.schema = schema or {"tables": []}

    def _get_tables(self):
        if isinstance(self.schema, dict):
            return self.schema.get("tables", [])
        elif hasattr(self.schema, "tables"):
            return self.schema.tables
        return []

    def _get_table_name(self, table) -> str:
        if isinstance(table, dict):
            return table.get("name", "")
        return getattr(table, "name", "")

    def _get_table_columns(self, table) -> list:
        if isinstance(table, dict):
            return table.get("columns", [])
        return getattr(table, "columns", [])

    def _get_column_name(self, col) -> str:
        if isinstance(col, dict):
            return col.get("name", "")
        return getattr(col, "name", "")

    def classify_intent(self, query: str) -> Dict[str, Any]:
        q_lower = query.strip().lower().rstrip("?.!")

        # --- REINDEX TRIGGER ---
        is_reindex = (
            any(t in q_lower for t in ["reindex", "re-index", "re index"]) or
            (("refresh" in q_lower or "reload" in q_lower or "update" in q_lower) and 
             ("db" in q_lower or "database" in q_lower or "schema" in q_lower or "table" in q_lower or "chatbot" in q_lower or "bot" in q_lower or "ai" in q_lower))
        )
        if is_reindex:
            return {"type": "reindex"}

        # 1. Greetings
        greetings = {
            "hello", "hi", "hey", "greetings", "good morning",
            "good afternoon", "good evening", "yo", "sup", "howdy"
        }
        if q_lower in greetings or any(q_lower.startswith(g + " ") for g in greetings):
            return {
                "type": "greeting",
                "response": "Hello! I am your AI Database Assistant. Connect a database and ask me any questions about your tables, columns, or metrics!"
            }

        # 2. Identity
        who_questions = {
            "who are you", "what is your name", "what do you do",
            "what are you", "tell me about yourself", "how do you work"
        }
        if any(wq in q_lower for wq in who_questions):
            return {
                "type": "greeting",
                "response": "I am an advanced Hybrid SQL + RAG Chatbot for industrial data analysis."
            }

        # 3. Help & List Tables
        help_keywords = {"help", "how to use", "instructions", "commands", "menu"}
        
        is_list_tables_query = (
            ("table" in q_lower or "tables" in q_lower) and
            any(w in q_lower for w in ["list", "show", "what", "connected", "active", "available", "ist", "give", "display", "get"]) and
            not any(m in q_lower for m in ["oee", "ega", "speed", "wastage", "waste", "downtime", "failed", "bags"]) and
            not any(t in q_lower for t in ["oee_details_data", "ega_details_data", "production_speed_details_data", "wastage_records", "gsm_usage_details"])
        )
        
        if q_lower in help_keywords or any(h in q_lower for h in help_keywords) or is_list_tables_query:
            tables = self._get_tables()
            table_list = ""
            if tables:
                names = [self._get_table_name(t) for t in tables]
                table_list = "\n\n**Connected Tables:**\n" + "\n".join(f"- `{n}`" for n in names)
            
            if is_list_tables_query:
                return {
                    "type": "greeting",
                    "response": f"Here are the active tables in the currently connected database:{table_list}"
                }
                
            return {
                "type": "greeting",
                "response": (
                    "Here's how you can query your database:\n"
                    "1. **Plain English Questions:** Ask directly\n"
                    "2. **Safety Measures:** Destructive actions are blocked\n"
                    "3. **Aggregate Metrics:** sums, averages, shifts, trends\n"
                    "4. **Type 'reindex'** to refresh schema after adding new tables"
                    f"{table_list}"
                )
            }

        # Extract schema keywords and DB generic terms early
        tables = self._get_tables()
        schema_keywords = set()
        if tables:
            for table in tables:
                t_name = self._get_table_name(table)
                schema_keywords.add(t_name.lower())
                for part in t_name.replace("_", " ").split():
                    if len(part) >= 2:
                        schema_keywords.add(part.lower())
                for col in self._get_table_columns(table):
                    c_name = self._get_column_name(col)
                    schema_keywords.add(c_name.lower())
                    for cpart in c_name.replace("_", " ").split():
                        if len(cpart) >= 2:
                            schema_keywords.add(cpart.lower())

        db_generic_words = {
            "query", "table", "database", "data", "row", "column", "select",
            "count", "average", "sum", "max", "min", "limit", "sort", "order",
            "list", "show", "find", "highest", "lowest", "most", "least",
            "compare", "total", "mean", "hourly", "daily", "monthly",
            "oee", "ega", "shift", "efficiency", "stopped", "downtime", "wastage",
            "employee", "operator", "speed"
        }

        q_clean = q_lower.replace("_", " ").replace("-", " ").replace("?", " ")
        words_in_query = set(q_clean.split())
        normalized = set()
        for w in words_in_query:
            normalized.add(w)
            if w.endswith("s") and len(w) > 3:
                normalized.add(w[:-1])
            if w.endswith("es") and len(w) > 4:
                normalized.add(w[:-2])

        has_db_term = (
            normalized.intersection(schema_keywords) or
            normalized.intersection(db_generic_words)
        )

        # 4. Conceptual RAG Route
        conceptual_prefixes = [
            "what is", "explain", "tell me about", "define",
            "what does", "what are", "how does", "why does",
            "meaning of", "can you explain"
        ]
        db_indicators = [
            "calculate", "show me", "sum", "average", "total", "count",
            "maximum", "minimum", "highest", "lowest", "limit", "record",
            "data in", "table", "value", "level", "percent", "%", "trend"
        ]
        is_conceptual = any(q_lower.startswith(p) for p in conceptual_prefixes)
        has_db_indicator = any(i in q_lower for i in db_indicators)
        if is_conceptual and not has_db_indicator and not has_db_term:
            return {"type": "conceptual"}

        # 5. Ambiguity Detection
        ambiguity = self._detect_ambiguity(q_lower)
        if ambiguity:
            return ambiguity

        # 6. Off-topic guardrail
        if tables:
            has_operators = any(
                op in q_lower for op in ("=", ">", "<", "percent", "%", "average", "sum")
            )

            if not has_db_term and not has_operators and len(words_in_query) > 2:
                return {
                    "type": "invalid_domain",
                    "response": (
                        "### 🔍 Industrial Domain Guardrail\n"
                        "I couldn't find a match for that in your factory schema.\n\n"
                        "I can help with:\n"
                        "📊 OEE & Production Performance\n"
                        "⚖️ Excess Giveaway Analysis (EGA)\n"
                        "⚡ Machine Production Speeds\n"
                        "🗑️ Material Wastage & Scrap Logs\n\n"
                        "Try: *'What is average OEE of machine 1?'*"
                    )
                }

        return {"type": "sql_query"}

    def _detect_ambiguity(self, q_lower: str) -> Optional[Dict]:
        filter_indicators = [
            ">", "<", "=", "above", "below", "greater", "less", "more than", 
            "higher than", "lower than", "at least", "at most", "limit", "filter"
        ]
        if any(fi in q_lower for fi in filter_indicators):
            return None

        is_short = len(q_lower.split()) <= 4
        machine_metrics = ["ega percent", "oee", "speed", "wastage"]
        machine_words = [
            "machine", "loop", "line", "m01", "m02", "m03", "l01", "l02", "l03"
        ]
        has_machine_metric = any(w in q_lower for w in machine_metrics)
        has_machine_specified = any(w in q_lower for w in machine_words)

        # Rule 1: Machine not specified
        if has_machine_metric and not has_machine_specified and is_short:
            return {
                "type": "clarification",
                "question": "Which machine or line do you want this for?",
                "suggestions": [
                    "All machines",
                    "Machine 1 (Loop 1)",
                    "Machine 2",
                    "Line 1"
                ],
                "original_query": q_lower
            }

        time_sensitive = ["ega", "oee", "efficiency", "production", "speed", "wastage"]
        time_words = [
            "today", "yesterday", "last week", "this week", "last month",
            "this month", "shift", "morning", "afternoon", "night",
            "last", "past", "recent", "from", "between", "since"
        ]
        has_time_sensitive = any(w in q_lower for w in time_sensitive)
        has_time_word = any(w in q_lower for w in time_words)

        # Rule 2: No time range
        if has_time_sensitive and not has_time_word and is_short:
            metric = next((w for w in time_sensitive if w in q_lower), "this metric")
            return {
                "type": "clarification",
                "question": f"What time range do you want for **{metric}**?",
                "suggestions": [
                    "Today",
                    "Yesterday",
                    "Last 7 days",
                    "This month",
                    "All time"
                ],
                "original_query": q_lower
            }

        # Rule 3: Vague "show me data"
        vague_triggers = ["show data", "get data", "show me data", "give data", "fetch data"]
        if any(t in q_lower for t in vague_triggers):
            return {
                "type": "clarification",
                "question": "What specific data are you looking for?",
                "suggestions": [
                    "EGA percent breakdown",
                    "OEE performance",
                    "Production speeds",
                    "Material wastage logs"
                ],
                "original_query": q_lower
            }

        # Rule 4: Comparison ambiguity
        compare_triggers = ["compare", "vs", "versus", "difference between"]
        if any(t in q_lower for t in compare_triggers):
            has_two_targets = sum(
                1 for w in machine_words if w in q_lower
            ) >= 2
            if not has_two_targets:
                return {
                    "type": "clarification",
                    "question": "What do you want to compare? Please specify both items.",
                    "suggestions": [
                        "Machine 1 vs Machine 2",
                        "Morning shift vs Night shift",
                        "This week vs Last week",
                        "Variant Flat Cut vs Ridge Cut"
                    ],
                    "original_query": q_lower
                }

        return None


class QuerySuggester:
    """
    Intelligent query suggestion engine that recommends follow-up questions
    based on current query results and schema context.
    """
    
    def __init__(self, schema: Dict):
        self.schema = schema
    
    def suggest_followups(self, user_query: str, sql: str, results: Dict, 
                          selected_tables: List[str]) -> List[str]:
        suggestions = []
        q_lower = user_query.lower()
        
        # 1. breakdowns
        if results.get("row_count") == 1 and results.get("rows"):
            row = results["rows"][0]
            if any(key in str(row.keys()).lower() for key in ["avg", "sum", "count", "total", "max", "min"]):
                suggestions.extend(self._suggest_breakdowns(selected_tables, user_query))
        
        # 2. time ranges
        if any(word in q_lower for word in ["today", "yesterday", "last week", "last month"]):
            suggestions.append("Show me the same data for last month")
            suggestions.append("Compare this week vs last week")
        
        # 3. specific entity
        if any(word in q_lower for word in ["machine", "line", "variant", "shift"]):
            suggestions.append("Compare all machines/variants side by side")
            suggestions.append("Which one has the highest/lowest value?")
        
        # 4. trends
        if results.get("rows") and len(results["rows"]) > 1:
            numeric_cols = [k for k, v in results["rows"][0].items() if isinstance(v, (int, float))]
            if numeric_cols:
                suggestions.append(f"Show me the trend of {numeric_cols[0]} over time")
                suggestions.append(f"Find anomalies in {numeric_cols[0]}")
        
        # 5. root cause
        if any(word in q_lower for word in ["low", "high", "problem", "issue", "error"]):
            suggestions.append("What factors correlate with this issue?")
            suggestions.append("When did this pattern start?")
        
        # 6. related metrics
        suggestions.extend(self._suggest_related_metrics(user_query))
        
        # 7. no results
        if results.get("row_count") == 0:
            suggestions.append("Show me all available data for this table")
            suggestions.append("What is the date range of available data?")
        
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:5]
    
    def _suggest_breakdowns(self, tables: List[str], query: str) -> List[str]:
        suggestions = []
        for table_name in tables:
            table = next((t for t in self.schema.get("tables", []) if t["name"] == table_name), None)
            if not table:
                continue
            
            categorical_cols = []
            for col in table.get("columns", []):
                col_name = col.get("name", "").lower()
                col_type = col.get("type", "").lower()
                
                if any(cat in col_name for cat in ["variant", "shift", "machine", "line", "zone", "type", "category", "status"]):
                    categorical_cols.append(col.get("name"))
                elif "varchar" in col_type or "text" in col_type or "char" in col_type:
                    categorical_cols.append(col.get("name"))
            
            for col in categorical_cols[:3]:
                if col.lower() not in query.lower():
                    suggestions.append(f"Break down by {col}")
        return suggestions
    
    def _suggest_related_metrics(self, query: str) -> List[str]:
        suggestions = []
        q_lower = query.lower()
        
        if any(word in q_lower for word in ["ega", "excess", "give away", "weight"]):
            suggestions.append("What is the average speed for the same period?")
            suggestions.append("Show me total production volume")
        
        if any(word in q_lower for word in ["speed", "rate", "throughput"]):
            suggestions.append("Calculate EGA percent for this data")
            suggestions.append("Show me target vs actual comparison")
        
        if any(word in q_lower for word in ["efficiency", "oee", "performance"]):
            suggestions.append("What is the downtime breakdown?")
            suggestions.append("Show me quality metrics")
        
        if any(word in q_lower for word in ["power", "energy", "electricity"]):
            suggestions.append("What is the cost breakdown by meter?")
            suggestions.append("Show me peak demand hours")
        
        return suggestions
    
    def suggest_exploratory_queries(self, table_name: str) -> List[str]:
        table = next((t for t in self.schema.get("tables", []) if t["name"] == table_name), None)
        if not table:
            return []
        
        suggestions = [
            f"Show me a summary of {table_name}",
            f"What is the date range of data in {table_name}?",
            f"How many records are in {table_name}?",
        ]
        
        columns = table.get("columns", [])
        numeric_cols = [c["name"] for c in columns if any(t in c.get("type", "").lower() for t in ["int", "float", "numeric", "decimal", "real"])]
        
        if numeric_cols:
            suggestions.append(f"What is the average {numeric_cols[0]}?")
            suggestions.append(f"Show me the distribution of {numeric_cols[0]}")
        
        return suggestions[:5]

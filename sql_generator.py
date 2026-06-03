import re
import json
import logging
import asyncio
from pathlib import Path
from litellm import acompletion
from backend.config import settings

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

class SQLGenerator:
    def __init__(self, db_connector):
        self.db = db_connector

    def sanitize_single_table_query(self, sql: str) -> str:
        sql_upper = sql.upper()
        # Avoid cleaning queries that have JOIN operations
        join_keywords = ["JOIN", "INNER", "LEFT", "RIGHT", "CROSS", "OUTER"]
        if any(re.search(rf"\b{kw}\b", sql_upper) for kw in join_keywords):
            return sql
            
        # Avoid cleaning queries that have multiple tables in FROM
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
            # Include sample rows for better LLM context
            if table.get("samples"):
                lines.append(f"  Sample row: {table['samples'][0]}")
        return "\n".join(lines)
    
    async def generate_sql(self, query: str, schema_info: dict, domain_hints: str, max_retries: int = 1, matched_tables: list = None) -> str:
        if matched_tables:
            domain_hints = f"{domain_hints}\n\nCONFIRMED RELEVANT TABLES TO USE: {', '.join(matched_tables)}"
        schema_text = self._format_schema(schema_info)
        prompt = SQL_SYSTEM_PROMPT.format(schema_text=schema_text, domain_hints=domain_hints)
        
        # Explicitly print and log enhanced_hints (domain_hints) and the full system prompt
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
            
            # Add self-correction context if previous attempt failed
            if last_error and last_sql:
                messages.append({"role": "assistant", "content": last_sql})
                messages.append({
                    "role": "user", 
                    "content": f"That SQL failed with error: {last_error}. Fix it and return ONLY the corrected SQL. DO NOT include any explanations, introduction, markdown code blocks, or conversational text. Start directly with SELECT."
                })
                logger.info(f"Retry attempt {attempt} with self-correction")
            
            try:
                response = await acompletion(
                    model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                    messages=messages,
                    api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                    temperature=0.0,
                    timeout=120
                )
                sql = response.choices[0].message.content.strip()
                
                # Clean up potential markdown formatting blocks generated by the LLM
                sql_blocks = re.findall(r"```sql\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                if not sql_blocks:
                    sql_blocks = re.findall(r"```\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                
                if sql_blocks:
                    # Robust extraction: the last block is typically the final corrected SQL candidate
                    sql = sql_blocks[-1].strip()
                else:
                    # No closed code blocks found. Let's see if there is an unclosed code block.
                    # An unclosed block starts with ```sql or ``` and doesn't have a closing ```
                    last_start = -1
                    marker_len = 0
                    for marker in ["```sql", "```SQL", "```"]:
                        idx = sql.rfind(marker)
                        if idx > last_start:
                            last_start = idx
                            marker_len = len(marker)
                    
                    if last_start != -1:
                        # Extract everything after the last code block start marker
                        sql = sql[last_start + marker_len:].strip()
                        # If there is a trailing unclosed marker at the end, remove it
                        sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                    else:
                        # If there are no markdown blocks at all, see if the text contains a SELECT statement
                        select_match = re.search(r"\bSELECT\b", sql, flags=re.IGNORECASE)
                        if select_match:
                            sql = sql[select_match.start():].strip()
                        else:
                            # Strip any leading ```sql or similar in case they are at the very beginning
                            sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"^```\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                
                # Trim semicolons and whitespaces
                sql = sql.strip().rstrip(";")
                
                # Sanitize single table queries to prevent alias/prefix mismatches
                sql = self.sanitize_single_table_query(sql)
                
                # Validate SQL with EXPLAIN dry-run before returning
                try:
                    await self.db.execute_query(f"EXPLAIN {sql}")
                    logger.info(f"Generated and validated SQL: {sql}")
                    return sql
                except Exception as validation_error:
                    last_error = str(validation_error)
                    last_sql = sql
                    
                    # Add helpful error context
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
                    
                    # If this was the last retry, raise the error
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
            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,  # Slightly higher for more creative suggestions
                timeout=120
            )
            explanation = response.choices[0].message.content.strip()
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
            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=120
            )
            return response.choices[0].message.content.strip()
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
            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=120
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error explanation generation failed: {e}")
            raise e

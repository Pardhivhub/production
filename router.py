import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class QueryRouter:
    def __init__(self, schema: dict = None):
        self.schema = schema or {"tables": []}

    def _get_tables(self):
        """Helper to safely fetch tables from either dict or Pydantic structures."""
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
        """
        Classifies user query intent to bypass the SQL execution stage for greetings,
        general chat, or invalid off-topic requests.
        """
        q_lower = query.strip().lower().rstrip("?.!")
        
        # 1. Casual greetings & simple conversation
        greetings = {
            "hello", "hi", "hey", "greetings", "good morning", "good afternoon", 
            "good evening", "yo", "sup", "howdy"
        }
        if q_lower in greetings or any(q_lower.startswith(g + " ") for g in greetings):
            return {
                "type": "greeting",
                "response": "Hello! I am your AI Database Assistant. Connect a database and ask me any questions about your tables, columns, or metrics, and I'll generate the precise queries and insights for you!"
            }
 
        # 2. Status / Identity checks
        who_questions = {
            "who are you", "what is your name", "what do you do", "what are you",
            "tell me about yourself", "how do you work"
        }
        if any(wq in q_lower for wq in who_questions):
            return {
                "type": "greeting",
                "response": "I am an advanced Asynchronous Hybrid SQL + RAG Chatbot. I help you query, analyze, and extract insights from your databases. You ask questions in plain English, and I write the perfect SQL, run it safely, and explain the results."
            }

        # 3. Help queries
        help_keywords = {"help", "how to use", "instructions", "commands", "menu"}
        if q_lower in help_keywords or any(h in q_lower for h in help_keywords):
            table_list = ""
            tables = self._get_tables()
            if tables:
                names = [self._get_table_name(t) for t in tables]
                table_list = f"\n\n**Connected Tables:**\n" + "\n".join(f"- `{n}`" for n in names)
            
            return {
                "type": "greeting",
                "response": (
                    "Here's how you can query your database:\n"
                    "1. **Plain English Questions:** Ask directly (e.g., *'Calculate OEE for morning shift on machine 1'*, *'What is excess give away percent breakdown'*, or *'What is the maximum peak demand?'*).\n"
                    "2. **Safety Measures:** Rest assured that destructive actions (like DROP or DELETE) are blocked by design.\n"
                    "3. **Aggregate Metrics:** You can ask for sums, averages, limits, standard deviations, and shifts."
                    f"{table_list}"
                )
            }

        # 4. Off-topic/Strict Mode Database Guardrail
        # Extract keywords from the connected schema to check domain relevance
        tables = self._get_tables()
        if tables:
            schema_keywords = set()
            for table in tables:
                t_name = self._get_table_name(table)
                # Add table name parts
                schema_keywords.add(t_name.lower())
                for part in t_name.replace("_", " ").split():
                    if len(part) > 2:
                        schema_keywords.add(part.lower())
                
                # Add column name parts
                columns = self._get_table_columns(table)
                for col in columns:
                    c_name = self._get_column_name(col)
                    schema_keywords.add(c_name.lower())
                    for cpart in c_name.replace("_", " ").split():
                        if len(cpart) > 2:
                            schema_keywords.add(cpart.lower())

            # Common database analytical words
            db_generic_words = {
                "query", "table", "database", "data", "row", "column", "select", 
                "count", "average", "sum", "max", "min", "limit", "sort", "order",
                "list", "show", "find", "highest", "lowest", "most", "least", "compare",
                "total", "mean", "hourly", "daily", "monthly", "january", "february",
                "oee", "ega", "shift", "efficiency", "stopped", "downtime", "wastage"
            }
            
            words_in_query = set(q_lower.replace("?", " ").replace(",", " ").split())
            
            # Check if there is any intersection with table/column keywords or generic db terminology
            has_db_term = words_in_query.intersection(schema_keywords) or words_in_query.intersection(db_generic_words)
            
            # Additional check: If query has numbers or common operators, let it pass
            has_operators = any(op in q_lower for op in ("=", ">", "<", "percent", "%", "average", "sum"))
            
            if not has_db_term and not has_operators and len(words_in_query) > 2:
                # Prompt is likely unrelated to the database schema
                table_names = ", ".join([f"`{self._get_table_name(t)}`" for t in tables])
                return {
                    "type": "invalid_domain",
                    "response": (
                        f"I detected that your query is likely unrelated to the connected database tables. "
                        f"Currently, I can query the following connected tables: {table_names}.\n\n"
                        f"Please ask a question related to these tables or their columns!"
                    )
                }

        return {"type": "sql_query"}

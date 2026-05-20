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

        # Check if the query is a general conceptual / RAG query
        conceptual_prefixes = [
            "what is", "explain", "tell me about", "define", "what does", 
            "what are", "how does", "why does", "meaning of", "can you explain"
        ]
        is_conceptual_prompt = any(q_lower.startswith(prefix) for prefix in conceptual_prefixes)
        
        # Ensure it's not a database query asking for calculations or lookups
        db_indicators = [
            "calculate", "show me", "sum", "average", "total", "count", 
            "maximum", "minimum", "highest", "lowest", "limit", "record", 
            "data in", "table", "value", "level"
        ]
        has_db_indicator = any(indicator in q_lower for indicator in db_indicators)
        
        if is_conceptual_prompt and not has_db_indicator:
            return {"type": "conceptual"}

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
                    if len(part) >= 2:
                        schema_keywords.add(part.lower())
                
                # Add column name parts
                columns = self._get_table_columns(table)
                for col in columns:
                    c_name = self._get_column_name(col)
                    schema_keywords.add(c_name.lower())
                    for cpart in c_name.replace("_", " ").split():
                        if len(cpart) >= 2:
                            schema_keywords.add(cpart.lower())

            # Common database analytical words
            db_generic_words = {
                "query", "table", "database", "data", "row", "column", "select", 
                "count", "average", "sum", "max", "min", "limit", "sort", "order",
                "list", "show", "find", "highest", "lowest", "most", "least", "compare",
                "total", "mean", "hourly", "daily", "monthly", "january", "february",
                "oee", "ega", "shift", "efficiency", "stopped", "downtime", "wastage"
            }
            
            # Replace underscores, hyphens, and other punctuation with spaces before splitting
            q_clean = q_lower.replace("_", " ").replace("-", " ").replace("?", " ").replace(",", " ").replace(".", " ")
            words_in_query = set(q_clean.split())
            
            # Singularize query words for robust plural matching (e.g. "feeders" -> "feeder")
            normalized_query_words = set()
            for w in words_in_query:
                normalized_query_words.add(w)
                if w.endswith("s") and len(w) > 3:
                    normalized_query_words.add(w[:-1])
                if w.endswith("es") and len(w) > 4:
                    normalized_query_words.add(w[:-2])
            
            # Check if there is any intersection with table/column keywords or generic db terminology
            has_db_term = normalized_query_words.intersection(schema_keywords) or normalized_query_words.intersection(db_generic_words)
            
            # Additional check: If query has numbers or common operators, let it pass
            has_operators = any(op in q_lower for op in ("=", ">", "<", "percent", "%", "average", "sum"))
            
            if not has_db_term and not has_operators and len(words_in_query) > 2:
                # Prompt is likely unrelated to the database schema
                friendly_message = (
                    "### 🔍 Industrial Domain Guardrail\n"
                    "I couldn't find a direct match for that query in your connected factory schema. "
                    "Since you may not know the physical table names, here are the main industrial areas I can help you analyze and query right now:\n\n"
                    "📊 **OEE & Production Performance** (actual vs target counts, speeds, OEE %, shift stats)\n"
                    "⚙️ **Feeder Calibration & Telemetry** (feeder amplitudes, weights, zero counts, worked counts)\n"
                    "⚡ **Energy & Utility Consumption** (electricity costs, hourly/daily kwh demand)\n"
                    "🍯 **Silo Inventory & Raw Materials** (sugar levels, packaging stock levels)\n"
                    "🌡️ **Environmental Logs** (humidity levels, temperatures, zone logs)\n"
                    "👥 **Staff Schedules & Certifications** (scheduled operator shifts, training levels)\n\n"
                    "💡 **Try asking a business question like:**\n"
                    "* *'What is the average OEE of weigher 3?'*\n"
                    "* *'Check the status and worked count for feeder 9.'*\n"
                    "* *'Show me our energy consumption and cost over the last week.'*\n"
                    "* *'Are there any silos that need refilling soon?'*\n\n"
                    "Please ask any question related to these topics, and I will automatically write the SQL and get your live results!"
                )
                return {
                    "type": "invalid_domain",
                    "response": friendly_message
                }

        return {"type": "sql_query"}

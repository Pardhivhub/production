import logging
from typing import Dict, Any, Optional

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
        
        # Highly robust check for table listing queries, even with typos like "ist all the tables"
        is_list_tables_query = (
            ("table" in q_lower or "tables" in q_lower) and
            any(w in q_lower for w in ["list", "show", "what", "connected", "active", "available", "ist", "give", "display", "get"])
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

        # Extract schema keywords and DB generic terms early for robust query routing
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
            "employee", "feeder", "operator"
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

        # 4. Conceptual — Only route as pure RAG conceptual if it has NO database or schema keywords!
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

        # 6. Off-topic guardrail (Reuses pre-calculated sets for extreme speed)
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
                        "⚙️ Feeder Calibration & Telemetry\n"
                        "⚡ Energy & Utility Consumption\n"
                        "🍯 Silo Inventory & Raw Materials\n"
                        "🌡️ Environmental Logs\n"
                        "👥 Staff Schedules & Certifications\n\n"
                        "Try: *'What is average OEE of weigher 3?'*"
                    )
                }

        return {"type": "sql_query"}

    # -----------------------------------------------------------------------
    # Ambiguity Detection Engine
    # -----------------------------------------------------------------------

    def _detect_ambiguity(self, q_lower: str) -> Optional[Dict]:
        """
        Detects genuinely ambiguous queries and returns a clarification
        request with suggestions. Returns None if query is clear enough.
        Only fires when truly needed — not on every query.
        """
        # Bypasses for specific data filters and comparison operators
        filter_indicators = [
            ">", "<", "=", "above", "below", "greater", "less", "more than", 
            "higher than", "lower than", "at least", "at most", "limit", "filter"
        ]
        if any(fi in q_lower for fi in filter_indicators):
            return None

        is_short = len(q_lower.split()) <= 4


        # Define metrics and words for Machine rule
        machine_metrics = ["ega percent", "amplitude", "feeder", "weigher"]
        machine_words = [
            "machine", "loop", "weigher", "line", "feeder",
            "m-1", "m-2", "m-3", "loop 1", "loop 2", "loop 3"
        ]
        has_machine_metric = any(w in q_lower for w in machine_metrics)
        has_machine_specified = any(w in q_lower for w in machine_words)

        # --- Ambiguity Rule 1: Machine/entity not specified (Prioritized) ---
        if has_machine_metric and not has_machine_specified and is_short:
            return {
                "type": "clarification",
                "question": "Which machine or line do you want this for?",
                "suggestions": [
                    "All machines",
                    "Machine 1 (Loop 1)",
                    "Machine 2 (Loop 2)",
                    "Machine 3 (Loop 3)"
                ],
                "original_query": q_lower
            }

        # Define metrics and words for Time rule
        time_sensitive = ["ega", "oee", "efficiency", "consumption", "cost", "production"]
        time_words = [
            "today", "yesterday", "last week", "this week", "last month",
            "this month", "january", "february", "march", "april", "may",
            "june", "july", "august", "september", "october", "november",
            "december", "shift", "morning", "afternoon", "night",
            "last", "past", "recent", "from", "between", "since"
        ]
        has_time_sensitive = any(w in q_lower for w in time_sensitive)
        has_time_word = any(w in q_lower for w in time_words)

        # --- Ambiguity Rule 2: No time range on time-sensitive metrics ---
        # Only reached if machine is already clear or not applicable
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

        # --- Ambiguity Rule 3: Vague "show me data" with no metric ---
        vague_triggers = ["show data", "get data", "show me data", "give data", "fetch data"]
        if any(t in q_lower for t in vague_triggers):
            return {
                "type": "clarification",
                "question": "What specific data are you looking for?",
                "suggestions": [
                    "EGA percent breakdown",
                    "OEE performance",
                    "Feeder amplitudes",
                    "Energy consumption",
                    "Silo inventory levels"
                ],
                "original_query": q_lower
            }

        # --- Ambiguity Rule 4: Comparison with no targets specified ---
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
                        "Variant A vs Variant B"
                    ],
                    "original_query": q_lower
                }

        return None

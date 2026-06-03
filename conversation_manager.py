# conversation_manager.py — replaces BOTH files
import logging
import re
from typing import List, Dict, Optional, Any
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Single unified conversation manager.
    Handles per-session memory, SQL history, and persistent constraints.
    Replaces both conversation_memory.py and the old conversation_manager.py.
    """

    def __init__(self, max_history: int = 20, max_turns: int = 3):
        self.max_history = max_history
        self.max_turns = max_turns

        # Full conversation history (for context window)
        self.conversation_history: List[Dict] = []

        # Per-session short-term memory (query, sql, result)
        self.sessions: Dict[str, deque] = {}

        # Persistent constraints — NOT cleared every message
        self.user_constraints: Dict[str, Any] = {}

        # Result cache keyed by SQL
        self.query_results_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Message Tracking
    # ------------------------------------------------------------------

    def add_user_message(self, message: str):
        self.conversation_history.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now()
        })
        self._extract_constraints(message)
        self._trim_history()

    def add_assistant_message(
        self,
        message: str,
        sql_query: Optional[str] = None,
        query_result: Optional[Dict] = None
    ):
        entry = {
            "role": "assistant",
            "content": message,
            "timestamp": datetime.now()
        }
        if sql_query:
            entry["sql_query"] = sql_query
        if query_result:
            entry["query_result"] = query_result
            if sql_query:
                self.query_results_cache[sql_query] = query_result

        self.conversation_history.append(entry)
        self._trim_history()

    # ------------------------------------------------------------------
    # Per-Session Short-Term Memory (replaces conversation_memory.py)
    # ------------------------------------------------------------------

    def add_turn(self, session_id: str, user_query: str, sql: str, result_summary: str):
        """Store a completed query turn for follow-up context."""
        if session_id not in self.sessions:
            self.sessions[session_id] = deque(maxlen=self.max_turns)
        self.sessions[session_id].append({
            "query": user_query,
            "sql": sql,
            "summary": result_summary
        })
        logger.info(f"Turn added to session {session_id} ({len(self.sessions[session_id])} turns)")

    def get_context(self, session_id: str) -> str:
        """
        Get short-term session memory for SQL generator.
        Used by conversation_memory.get_context() callers.
        """
        if session_id not in self.sessions or not self.sessions[session_id]:
            return ""

        lines = ["RECENT QUERY HISTORY (use for follow-up questions):"]
        for i, turn in enumerate(self.sessions[session_id], 1):
            lines.append(f"\nTurn {i}:")
            lines.append(f"  User asked: {turn['query']}")
            lines.append(f"  SQL used:   {turn['sql']}")
            lines.append(f"  Result:     {turn['summary']}")
        return "\n".join(lines)

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Session {session_id} cleared")

    # ------------------------------------------------------------------
    # Constraint Extraction — PERSISTENT, not cleared every message
    # ------------------------------------------------------------------

    def _extract_constraints(self, message: str):
        """
        Extract constraints from message and ADD them.
        Global preferences (like no_joins) persist, while query-specific
        constraints (like target_table, operation, time_filter, target_machine, target_variant)
        are cleared at the start of each turn so they do not leak into unrelated future queries.
        """
        # Clear query-specific constraints so they don't persist across unrelated turns
        for key in ["target_table", "operation", "time_filter", "target_machine", "target_variant"]:
            self.user_constraints.pop(key, None)

        message_lower = message.lower()

        # JOIN constraints
        if any(p in message_lower for p in ["don't join", "dont join", "no join", "without join", "avoid join"]):
            self.user_constraints["no_joins"] = True
            logger.info("Constraint set: no_joins=True")

        # Explicit join re-enable
        if any(p in message_lower for p in ["use join", "with join", "allow join", "joins ok"]):
            self.user_constraints.pop("no_joins", None)
            logger.info("Constraint cleared: no_joins")

        # Target table
        table_patterns = {
            "ega": "ega_details_data",
            "oee": "oee_details_data",
            "speed": "production_speed_details_data",
            "wastage": "wastage_records",
            "gsm": "gsm_usage_details",
            "flavour": "flavours",
            "machine": "machines",
            "employee": "employees_list"
        }
        if "table" in message_lower or "from" in message_lower:
            for keyword, table_name in table_patterns.items():
                if keyword in message_lower:
                    self.user_constraints["target_table"] = table_name
                    logger.info(f"Constraint set: target_table={table_name}")
                    break

        # Operation type
        if "count" in message_lower and "unique" in message_lower:
            self.user_constraints["operation"] = "count_distinct"
        elif "count" in message_lower:
            self.user_constraints["operation"] = "count"

        # Time window — extract and persist
        time_map = {
            "today": "DATE(timestamp_col) = CURRENT_DATE",
            "yesterday": "DATE(timestamp_col) = CURRENT_DATE - INTERVAL '1 day'",
            "last week": "timestamp_col >= NOW() - INTERVAL '7 days'",
            "last month": "timestamp_col >= NOW() - INTERVAL '30 days'",
            "this week": "timestamp_col >= DATE_TRUNC('week', CURRENT_DATE)",
            "this month": "timestamp_col >= DATE_TRUNC('month', CURRENT_DATE)",
        }
        for phrase, sql_filter in time_map.items():
            if phrase in message_lower:
                self.user_constraints["time_filter"] = phrase
                break

        # Machine/loop specification
        machine_match = re.search(
            r"\b(loop\s?\d+|machine\s?\d+|weigher\s?\d+|line\s?\d+|m-\d+)\b",
            message_lower
        )
        if machine_match:
            self.user_constraints["target_machine"] = machine_match.group(1).strip()
            logger.info(f"Constraint set: target_machine={self.user_constraints['target_machine']}")

        # Variant/product specification
        variant_match = re.search(r"\bvariant\s+([a-z0-9\-]+)\b", message_lower)
        if variant_match:
            self.user_constraints["target_variant"] = variant_match.group(1).upper()
            logger.info(f"Constraint set: target_variant={self.user_constraints['target_variant']}")

    # ------------------------------------------------------------------
    # Context Building For LLM
    # ------------------------------------------------------------------

    def get_conversation_context(self, last_n: Optional[int] = None) -> str:
        """
        Build full context string for LLM prompt injection.
        Includes active constraints + recent conversation history.
        """
        history = self.conversation_history[-last_n:] if last_n else self.conversation_history
        parts = []

        # Active constraints first — most important for SQL generation
        if self.user_constraints:
            parts.append("ACTIVE USER CONSTRAINTS (always respect these):")
            for key, value in self.user_constraints.items():
                parts.append(f"  - {key}: {value}")
            parts.append("")

        # Recent conversation
        if history:
            parts.append("RECENT CONVERSATION:")
            for entry in history:
                role = entry["role"].upper()
                content = entry["content"][:200]  # truncate long messages
                parts.append(f"{role}: {content}")
                if "sql_query" in entry:
                    parts.append(f"  → SQL: {entry['sql_query'][:150]}")
                if "query_result" in entry:
                    parts.append(f"  → {entry['query_result'].get('row_count', 0)} rows returned")
                parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_active_constraints(self) -> Dict[str, Any]:
        return self.user_constraints.copy()

    def clear_constraint(self, key: str):
        self.user_constraints.pop(key, None)
        logger.info(f"Constraint cleared: {key}")

    def clear_all_constraints(self):
        self.user_constraints.clear()
        logger.info("All constraints cleared")

    def get_last_query_result(self) -> Optional[Dict]:
        for entry in reversed(self.conversation_history):
            if entry["role"] == "assistant" and "query_result" in entry:
                return entry["query_result"]
        return None

    def should_use_joins(self) -> bool:
        return not self.user_constraints.get("no_joins", False)

    def get_target_table(self) -> Optional[str]:
        return self.user_constraints.get("target_table")

    def get_target_machine(self) -> Optional[str]:
        return self.user_constraints.get("target_machine")

    def get_target_variant(self) -> Optional[str]:
        return self.user_constraints.get("target_variant")

    def _trim_history(self):
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

    def get_summary(self) -> Dict:
        return {
            "message_count": len(self.conversation_history),
            "active_constraints": self.user_constraints,
            "cached_queries": len(self.query_results_cache),
            "sessions": list(self.sessions.keys()),
            "last_interaction": (
                self.conversation_history[-1]["timestamp"].isoformat()
                if self.conversation_history else None
            )
        }

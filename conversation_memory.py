# conversation_memory.py
import logging
from typing import List, Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)

class ConversationMemory:
    """
    Manages conversation history for context-aware follow-up questions.
    Stores last N turns (question, SQL, results summary) per session.
    """
    def __init__(self, max_turns: int = 3):
        self.max_turns = max_turns
        self.sessions: Dict[str, deque] = {}
    
    def add_turn(self, session_id: str, user_query: str, sql: str, result_summary: str):
        """Add a conversation turn to the session history."""
        if session_id not in self.sessions:
            self.sessions[session_id] = deque(maxlen=self.max_turns)
        
        self.sessions[session_id].append({
            "query": user_query,
            "sql": sql,
            "summary": result_summary
        })
        logger.info(f"Added turn to session {session_id}. History size: {len(self.sessions[session_id])}")
    
    def get_context(self, session_id: str) -> str:
        """Get formatted conversation history for LLM context."""
        if session_id not in self.sessions or not self.sessions[session_id]:
            return ""
        
        history_lines = ["CONVERSATION HISTORY (for context on follow-up questions):"]
        for i, turn in enumerate(self.sessions[session_id], 1):
            history_lines.append(f"\nTurn {i}:")
            history_lines.append(f"  User asked: {turn['query']}")
            history_lines.append(f"  SQL executed: {turn['sql']}")
            history_lines.append(f"  Result: {turn['summary']}")
        
        return "\n".join(history_lines)
    
    def clear_session(self, session_id: str):
        """Clear conversation history for a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Cleared session {session_id}")

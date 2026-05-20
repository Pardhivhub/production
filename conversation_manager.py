import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation history and user constraints for context-aware responses"""
    
    def __init__(self, max_history: int = 20):
        self.max_history = max_history
        self.conversation_history: List[Dict] = []
        self.user_constraints: Dict[str, any] = {}
        self.query_results_cache: Dict[str, Dict] = {}
        
    def add_user_message(self, message: str, timestamp: Optional[datetime] = None):
        """Add user message and extract constraints"""
        if timestamp is None:
            timestamp = datetime.now()
            
        self.conversation_history.append({
            "role": "user",
            "content": message,
            "timestamp": timestamp
        })
        
        # Extract and store user constraints
        self._extract_constraints(message)
        self._trim_history()
        
    def add_assistant_message(self, message: str, sql_query: Optional[str] = None, 
                             query_result: Optional[Dict] = None, timestamp: Optional[datetime] = None):
        """Add assistant response with optional SQL and results"""
        if timestamp is None:
            timestamp = datetime.now()
            
        entry = {
            "role": "assistant",
            "content": message,
            "timestamp": timestamp
        }
        
        if sql_query:
            entry["sql_query"] = sql_query
            
        if query_result:
            entry["query_result"] = query_result
            # Cache the result
            self.query_results_cache[sql_query] = query_result
            
        self.conversation_history.append(entry)
        self._trim_history()
        
    def _extract_constraints(self, message: str):
        """Extract user constraints from message"""
        # Clear previous constraints to avoid stale constraint bleeding into subsequent turns
        self.user_constraints.clear()
        
        message_lower = message.lower()
        
        # Check for JOIN constraints
        if any(phrase in message_lower for phrase in ["don't join", "dont join", "no join", "without join", "avoid join"]):
            self.user_constraints["no_joins"] = True
            logger.info("User constraint detected: NO JOINS")
            
        # Check for specific table mentions
        if "feedback" in message_lower and "table" in message_lower:
            self.user_constraints["target_table"] = "feedback_data"
            logger.info("User constraint detected: Target table = feedback_data")
            
        # Check for COUNT operations
        if "count" in message_lower and "unique" in message_lower:
            self.user_constraints["operation"] = "count_distinct"
            logger.info("User constraint detected: COUNT DISTINCT operation")
            
        # Check for specific columns
        if "feeder" in message_lower:
            self.user_constraints["target_column"] = "feeder"
            logger.info("User constraint detected: Target column contains 'feeder'")
    
    def get_active_constraints(self) -> Dict[str, any]:
        """Return currently active user constraints"""
        return self.user_constraints.copy()
    
    def clear_constraint(self, constraint_key: str):
        """Remove a specific constraint"""
        if constraint_key in self.user_constraints:
            del self.user_constraints[constraint_key]
            logger.info(f"Cleared constraint: {constraint_key}")
    
    def clear_all_constraints(self):
        """Clear all constraints"""
        self.user_constraints.clear()
        logger.info("All constraints cleared")
        
    def get_conversation_context(self, last_n: Optional[int] = None) -> str:
        """Get formatted conversation history for LLM context"""
        history = self.conversation_history[-last_n:] if last_n else self.conversation_history
        
        context_parts = []
        
        # Add active constraints first
        if self.user_constraints:
            context_parts.append("ACTIVE USER CONSTRAINTS:")
            for key, value in self.user_constraints.items():
                context_parts.append(f"  - {key}: {value}")
            context_parts.append("")
        
        # Add conversation history
        context_parts.append("CONVERSATION HISTORY:")
        for entry in history:
            role = entry["role"].upper()
            content = entry["content"]
            context_parts.append(f"{role}: {content}")
            
            if "sql_query" in entry:
                context_parts.append(f"  SQL: {entry['sql_query']}")
            if "query_result" in entry:
                context_parts.append(f"  RESULT: {entry['query_result'].get('row_count', 0)} rows")
            context_parts.append("")
            
        return "\n".join(context_parts)
    
    def get_last_query_result(self) -> Optional[Dict]:
        """Get the most recent query result"""
        for entry in reversed(self.conversation_history):
            if entry["role"] == "assistant" and "query_result" in entry:
                return entry["query_result"]
        return None
    
    def _trim_history(self):
        """Keep only the most recent messages"""
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]
            
    def should_use_joins(self) -> bool:
        """Check if joins are allowed based on constraints"""
        return not self.user_constraints.get("no_joins", False)
    
    def get_target_table(self) -> Optional[str]:
        """Get the target table if specified"""
        return self.user_constraints.get("target_table")
    
    def get_summary(self) -> Dict:
        """Get a summary of the conversation state"""
        return {
            "message_count": len(self.conversation_history),
            "active_constraints": self.user_constraints,
            "cached_queries": len(self.query_results_cache),
            "last_interaction": self.conversation_history[-1]["timestamp"] if self.conversation_history else None
        }

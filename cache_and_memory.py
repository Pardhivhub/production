"""
Memory & Caching Layer - Implements Semantic Cache and Unified Conversation Manager
"""
import logging
import hashlib
import json
import asyncio
import re
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from collections import deque
import numpy as np
from sqlalchemy import text

logger = logging.getLogger(__name__)

class QueryCache:
    """
    Semantic Query Cache using embedding similarity.
    Integrates with PostgreSQL or falls back to in-memory/Python calculation.
    """
    def __init__(self, db_connector=None, ttl_minutes: int = 60, similarity_threshold: float = 0.995):
        self.db = db_connector
        self.ttl = timedelta(minutes=ttl_minutes)
        self.similarity_threshold = similarity_threshold
        
        # In-memory hot cache fallback
        self.memory_cache: Dict[str, Dict] = {}
        
        # Embedding function lazy-loaded
        self._ef = None
        self.vector_enabled = False
        self.db_initialized = False

    @property
    def ef(self):
        if self._ef is None:
            try:
                from search_and_rag import OllamaEmbeddingFunction
                from backend.config import settings
                self._ef = OllamaEmbeddingFunction(
                    model_name="all-minilm:latest",
                    url=f"{settings.OLLAMA_BASE_URL}/api/embeddings"
                )
                logger.info("Semantic cache loaded OllamaEmbeddingFunction successfully.")
            except Exception as e:
                logger.error(f"Failed to load embedding function for cache: {e}")
        return self._ef

    async def initialize_db(self):
        """Creates semantic cache table, attempting pgvector first, falling back to text representation."""
        if not self.db or self.db_initialized:
            return

        try:
            # 1. Try to check pgvector extension
            try:
                await self.db.execute_write("CREATE EXTENSION IF NOT EXISTS vector")
                await self.db.execute_write("""
                    CREATE TABLE IF NOT EXISTS semantic_query_cache (
                        id SERIAL PRIMARY KEY,
                        query_text TEXT UNIQUE,
                        query_embedding VECTOR(384),
                        generated_sql TEXT,
                        cached_results JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.vector_enabled = True
                logger.info("✓ pgvector enabled semantic cache successfully created.")
            except Exception as ex:
                logger.warning(f"pgvector not available, falling back to standard text embedding storage. Error: {ex}")
                # Fallback schema (embedding as serialized float JSON list)
                await self.db.execute_write("""
                    CREATE TABLE IF NOT EXISTS semantic_query_cache (
                        id SERIAL PRIMARY KEY,
                        query_text TEXT UNIQUE,
                        query_embedding TEXT,
                        generated_sql TEXT,
                        cached_results JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.vector_enabled = False
                logger.info("✓ Text-based embedding storage created for fallback semantic caching.")
            
            self.db_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize semantic cache database tables: {e}")

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two float vectors."""
        try:
            arr1 = np.array(v1)
            arr2 = np.array(v2)
            dot = np.dot(arr1, arr2)
            norm1 = np.linalg.norm(arr1)
            norm2 = np.linalg.norm(arr2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(dot / (norm1 * norm2))
        except Exception as e:
            logger.error(f"Cosine similarity calculation failed: {e}")
            return 0.0

    async def get_semantic(self, query: str) -> Optional[Dict]:
        """Find a semantically matching cached query."""
        if not query or not self.ef:
            return None

        # 1. Look in hot in-memory cache first (exact string match for speed)
        clean_q = query.strip().lower()
        for key, entry in self.memory_cache.items():
            if key == clean_q and datetime.now() - entry["timestamp"] < self.ttl:
                logger.info("Semantic Cache: Exact string match HIT in memory.")
                return entry["result"]

        # 2. Get query embedding
        try:
            emb_list = self.ef([query])
            if not emb_list or len(emb_list) == 0:
                return None
            embedding = emb_list[0]
        except Exception as e:
            logger.error(f"Failed to compute embedding for lookup: {e}")
            return None

        # 3. Query PostgreSQL if initialized
        if self.db and self.db_initialized:
            try:
                if self.vector_enabled:
                    # Execute semantic search using pgvector operator <=> (cosine distance)
                    emb_str = "[" + ",".join(map(str, embedding)) + "]"
                    sql = """
                        SELECT query_text, generated_sql, cached_results, created_at,
                               1 - (query_embedding <=> CAST(:embedding AS vector)) AS similarity
                        FROM semantic_query_cache
                        WHERE created_at >= NOW() - INTERVAL '1 hour'
                        ORDER BY query_embedding <=> CAST(:embedding AS vector) LIMIT 1
                    """
                    # Direct query using engine to execute bound parameters
                    async with self.db.engine.connect() as conn:
                        res = await conn.execute(text(sql), {"embedding": emb_str})
                        row = res.first()
                        if row:
                            sim = row.similarity
                            if sim >= self.similarity_threshold:
                                logger.info(f"Semantic Cache: pgvector HIT (similarity={sim:.4f})")
                                return {
                                    "sql": row.generated_sql,
                                    "results": row.cached_results
                                }
                else:
                    # Non-pgvector fallback: fetch recent rows and calculate similarity in Python
                    sql = """
                        SELECT query_text, query_embedding, generated_sql, cached_results, created_at
                        FROM semantic_query_cache
                        WHERE created_at >= NOW() - INTERVAL '1 hour'
                        ORDER BY id DESC LIMIT 500
                    """
                    res = await self.db.execute_query(sql)
                    if res.get("rows"):
                        best_match = None
                        best_sim = -1.0
                        for row in res["rows"]:
                            try:
                                db_emb = json.loads(row["query_embedding"])
                                sim = self._cosine_similarity(embedding, db_emb)
                                if sim > best_sim:
                                    best_sim = sim
                                    best_match = row
                            except Exception:
                                continue
                        
                        if best_match and best_sim >= self.similarity_threshold:
                            logger.info(f"Semantic Cache: Fallback HIT (similarity={best_sim:.4f})")
                            return {
                                    "sql": best_match["generated_sql"],
                                    "results": best_match["cached_results"]
                                }
            except Exception as e:
                logger.error(f"Semantic Cache DB lookup error: {e}")

        # 4. Fallback: Python cosine similarity scan over memory cache keys
        best_sim = -1.0
        best_match = None
        for key, entry in self.memory_cache.items():
            if datetime.now() - entry["timestamp"] < self.ttl:
                sim = self._cosine_similarity(embedding, entry["embedding"])
                if sim > best_sim:
                    best_sim = sim
                    best_match = entry["result"]

        if best_match and best_sim >= self.similarity_threshold:
            logger.info(f"Semantic Cache: Memory scan HIT (similarity={best_sim:.4f})")
            return best_match

        logger.info("Semantic Cache: MISS.")
        return None

    async def set_semantic(self, query: str, sql: str, results: Dict):
        """Store query details, SQL, results, and embedding in the semantic cache."""
        if not query or not sql or not self.ef:
            return

        clean_q = query.strip().lower()
        
        # Get query embedding
        try:
            emb_list = self.ef([query])
            if not emb_list or len(emb_list) == 0:
                return
            embedding = emb_list[0]
        except Exception as e:
            logger.error(f"Failed to embed query for cache storage: {e}")
            return

        # Store in memory hot cache
        self.memory_cache[clean_q] = {
            "result": {"sql": sql, "results": results},
            "embedding": embedding,
            "timestamp": datetime.now()
        }

        # Store in PostgreSQL database
        if self.db and self.db_initialized:
            try:
                results_json = json.dumps(results)
                if self.vector_enabled:
                    emb_str = "[" + ",".join(map(str, embedding)) + "]"
                    insert_sql = """
                        INSERT INTO semantic_query_cache (query_text, query_embedding, generated_sql, cached_results)
                        VALUES (:query, CAST(:embedding AS vector), :sql, :results)
                        ON CONFLICT (query_text) DO UPDATE 
                        SET query_embedding = EXCLUDED.query_embedding,
                            generated_sql = EXCLUDED.generated_sql,
                            cached_results = EXCLUDED.cached_results,
                            created_at = CURRENT_TIMESTAMP
                    """
                    await self.db.execute_write(insert_sql, {
                        "query": query,
                        "embedding": emb_str,
                        "sql": sql,
                        "results": results_json
                    })
                else:
                    emb_json = json.dumps(embedding)
                    insert_sql = """
                        INSERT INTO semantic_query_cache (query_text, query_embedding, generated_sql, cached_results)
                        VALUES (:query, :embedding, :sql, :results)
                        ON CONFLICT (query_text) DO UPDATE 
                        SET query_embedding = EXCLUDED.query_embedding,
                            generated_sql = EXCLUDED.generated_sql,
                            cached_results = EXCLUDED.cached_results,
                            created_at = CURRENT_TIMESTAMP
                    """
                    await self.db.execute_write(insert_sql, {
                        "query": query,
                        "embedding": emb_json,
                        "sql": sql,
                        "results": results_json
                    })
                logger.info("Stored query in DB semantic cache.")
            except Exception as e:
                logger.warning(f"Could not persist semantic cache row to DB: {e}")

    def clear(self):
        """Clear all cached entries."""
        self.memory_cache.clear()
        logger.info("Semantic cache memory cleared.")


class ConversationManager:
    """
    Unified conversation manager with PostgreSQL persistent history.
    Handles per-session memory, SQL history, and persistent constraints.
    """
    def __init__(self, db_connector=None, max_history: int = 20, max_turns: int = 3):
        self.db = db_connector
        self.max_history = max_history
        self.max_turns = max_turns
        self.db_initialized = False

        # Local cache for rapid access within a request
        self.conversation_history: List[Dict] = []
        self.sessions: Dict[str, deque] = {}
        self.user_constraints: Dict[str, Any] = {}
        self.query_results_cache: Dict[str, Dict] = {}

    async def initialize_db(self):
        """Creates the persistent conversation history table in PostgreSQL."""
        if not self.db or self.db_initialized:
            return
        try:
            await self.db.execute_write("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255),
                    role VARCHAR(50),
                    content TEXT,
                    sql_query TEXT,
                    query_result JSONB,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db_initialized = True
            logger.info("✓ Persistent conversation memory table initialized in database.")
        except Exception as e:
            logger.error(f"Failed to initialize conversation memory table: {e}")

    async def load_history_from_db(self, session_id: str):
        """Load conversation history for this session from PostgreSQL."""
        if not self.db or not self.db_initialized or not session_id:
            return
        try:
            sql = """
                SELECT role, content, sql_query, query_result, timestamp
                FROM conversation_turns
                WHERE session_id = :session_id
                ORDER BY timestamp ASC LIMIT :limit
            """
            async with self.db.engine.connect() as conn:
                result = await conn.execute(text(sql), {
                    "session_id": session_id,
                    "limit": self.max_history
                })
                self.conversation_history = []
                for row in result.all():
                    entry = {
                        "role": row.role,
                        "content": row.content,
                        "timestamp": row.timestamp
                    }
                    if row.sql_query:
                        entry["sql_query"] = row.sql_query
                    if row.query_result:
                        if isinstance(row.query_result, str):
                            try:
                                entry["query_result"] = json.loads(row.query_result)
                            except Exception:
                                entry["query_result"] = row.query_result
                        else:
                            entry["query_result"] = row.query_result
                    self.conversation_history.append(entry)
            logger.info(f"Loaded {len(self.conversation_history)} history turns for session {session_id} from DB.")
        except Exception as e:
            logger.warning(f"Could not load conversation history from DB: {e}")

    async def add_user_message(self, message: str, session_id: Optional[str] = None):
        """Add user message to history and persist to PostgreSQL."""
        self.conversation_history.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now()
        })
        self._extract_constraints(message)
        self._trim_history()

        if self.db and self.db_initialized and session_id:
            try:
                sql = """
                    INSERT INTO conversation_turns (session_id, role, content)
                    VALUES (:session_id, 'user', :content)
                """
                await self.db.execute_write(sql, {
                    "session_id": session_id,
                    "content": message
                })
            except Exception as e:
                logger.warning(f"Failed to persist user message to DB: {e}")

    async def add_assistant_message(
        self,
        message: str,
        sql_query: Optional[str] = None,
        query_result: Optional[Dict] = None,
        session_id: Optional[str] = None
    ):
        """Add assistant response to history and persist to PostgreSQL."""
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

        if self.db and self.db_initialized and session_id:
            try:
                sql = """
                    INSERT INTO conversation_turns (session_id, role, content, sql_query, query_result)
                    VALUES (:session_id, 'assistant', :content, :sql_query, :query_result)
                """
                res_json = json.dumps(query_result) if query_result else None
                await self.db.execute_write(sql, {
                    "session_id": session_id,
                    "content": message,
                    "sql_query": sql_query,
                    "query_result": res_json
                })
            except Exception as e:
                logger.warning(f"Failed to persist assistant message to DB: {e}")

    def add_turn(self, session_id: str, user_query: str, sql: str, result_summary: str):
        """Store a completed query turn for follow-up context in memory."""
        if session_id not in self.sessions:
            self.sessions[session_id] = deque(maxlen=self.max_turns)
        self.sessions[session_id].append({
            "query": user_query,
            "sql": sql,
            "summary": result_summary
        })
        logger.info(f"Turn added to session {session_id} ({len(self.sessions[session_id])} turns)")

    def get_context(self, session_id: str) -> str:
        """Get short-term session memory for SQL generator."""
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

    def _extract_constraints(self, message: str):
        # Clear query-specific constraints so they don't persist across unrelated turns
        for key in ["target_table", "operation", "time_filter", "target_machine", "target_variant"]:
            self.user_constraints.pop(key, None)

        message_lower = message.lower()

        # JOIN constraints
        if any(p in message_lower for p in ["don't join", "dont join", "no join", "without join", "avoid join"]):
            self.user_constraints["no_joins"] = True
            logger.info("Constraint set: no_joins=True")

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

        # Time window
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

    def get_conversation_context(self, last_n: Optional[int] = None) -> str:
        history = self.conversation_history[-last_n:] if last_n else self.conversation_history
        parts = []

        if self.user_constraints:
            parts.append("ACTIVE USER CONSTRAINTS (always respect these):")
            for key, value in self.user_constraints.items():
                parts.append(f"  - {key}: {value}")
            parts.append("")

        if history:
            parts.append("RECENT CONVERSATION:")
            for entry in history:
                role = entry["role"].upper()
                content = entry["content"][:200]
                parts.append(f"{role}: {content}")
                if "sql_query" in entry:
                    parts.append(f"  → SQL: {entry['sql_query'][:150]}")
                if "query_result" in entry:
                    parts.append(f"  → {entry['query_result'].get('row_count', 0)} rows returned")
                parts.append("")

        return "\n".join(parts)

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

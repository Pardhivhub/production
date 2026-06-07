# query_cache.py
import logging
import hashlib
import json
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)

class QueryCache:
    """
    Semantic Query Cache using embedding similarity.
    Integrates with PostgreSQL or falls back to in-memory/Python calculation.
    """
    def __init__(self, db_connector=None, ttl_minutes: int = 60, similarity_threshold: float = 0.96):
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
                from embedder import OllamaEmbeddingFunction
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

# Add compatibility import for text operator
from sqlalchemy import text

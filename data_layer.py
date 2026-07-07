from backend.config import settings
from collections import deque
from datetime import datetime, timedelta
from litellm import acompletion
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from typing import Dict, List, Optional
from typing import Optional, Dict, List, Any
import asyncio
import hashlib
import json
import logging
import numpy as np
import re

"""
Database & Semantic Layer - Manages database connections, schema extraction, and business metadata enrichment
"""

logger = logging.getLogger(__name__)

class DatabaseConnector:
    def __init__(self, db_url: str):
        # Format the SQLite or Postgres URL for async drivers
        if db_url.startswith("sqlite"):
            if not db_url.startswith("sqlite+aiosqlite://"):
                if db_url.startswith("sqlite:///"):
                    self.db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
                else:
                    self.db_url = f"sqlite+aiosqlite:///{db_url}"
            else:
                self.db_url = db_url
        elif db_url.startswith("postgresql") or db_url.startswith("postgres"):
            if not db_url.startswith("postgresql+asyncpg://"):
                self.db_url = db_url.replace("postgresql://", "postgresql+asyncpg://").replace("postgres://", "postgresql+asyncpg://")
            else:
                self.db_url = db_url
        else:
            raise ValueError("Unsupported database type. Please use SQLite or PostgreSQL URL.")
            
        self.engine: AsyncEngine = None

    async def connect(self):
        try:
            logger.info(f"Connecting to database via URL: {self.db_url}")
            if "asyncpg" in self.db_url:
                self.engine = create_async_engine(self.db_url, connect_args={"server_settings": {"search_path": "itciot"}})
            else:
                self.engine = create_async_engine(self.db_url)
            # Verify the connection instantly
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Successfully connected to the database.")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise e

    async def execute_query(self, sql_query: str) -> dict:
        if not self.engine:
            raise RuntimeError("Database not connected. Please connect first.")
            
        # Enforce read-only safety guardrail
        lower_query = sql_query.lower()
        import re
        destructive_keywords = [r"\bdrop\b", r"\bdelete\b", r"\btruncate\b", r"\bupdate\b", r"\binsert\b", r"\balter\b", r"\bcreate\b"]
        if any(re.search(pattern, lower_query) for pattern in destructive_keywords):
            raise ValueError("Destructive write operations are strictly blocked for security.")

        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(text(sql_query))
                
                # If query returns rows
                if result.returns_rows:
                    columns = list(result.keys())
                    rows = []
                    for row in result.all():
                        # Map row values to columns and serialize decimals
                        row_dict = {}
                        for col, val in zip(columns, row):
                            # Convert decimal and datetime values for JSON serialization
                            if hasattr(val, "quantize") or type(val).__name__ == "Decimal":
                                row_dict[col] = float(val)
                            elif hasattr(val, "isoformat"):
                                row_dict[col] = val.isoformat()
                            else:
                                row_dict[col] = val
                        rows.append(row_dict)
                        
                    return {
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows)
                    }
                else:
                    return {
                        "columns": [],
                        "rows": [],
                        "row_count": 0
                    }
        except Exception as e:
            logger.error(f"Failed to execute SQL: {sql_query}. Error: {e}")
            raise e

    async def execute_write(self, sql_query: str, params: dict = None) -> dict:
        """Executes system write queries (bypass guardrail for caching and conversation history)."""
        if not self.engine:
            raise RuntimeError("Database not connected. Please connect first.")
            
        try:
            async with self.engine.connect() as conn:
                if params:
                    result = await conn.execute(text(sql_query), params)
                else:
                    result = await conn.execute(text(sql_query))
                await conn.commit()
                return {
                    "row_count": result.rowcount if hasattr(result, "rowcount") else 0
                }
        except Exception as e:
            logger.error(f"Failed to execute SQL write: {sql_query}. Error: {e}")
            raise e

    async def get_schema_metadata(self) -> dict:
        """Retrieves raw tables and columns to populate the schema and guide the AI."""
        if not self.engine:
            raise RuntimeError("Database not connected. Please connect first.")
            
        tables = []
        try:
            async with self.engine.connect() as conn:
                # Retrieve tables list depending on dialect
                dialect = self.engine.dialect.name
                if dialect == "sqlite":
                    query_tables = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
                else:  # Postgres
                    query_tables = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'itciot';"
                
                res_tables = await conn.execute(text(query_tables))
                table_names = list(set([r[0] for r in res_tables.all()]))
                
                # Retrieve column info for each table
                for table in table_names:
                    columns = []
                    if dialect == "sqlite":
                        res_cols = await conn.execute(text(f"PRAGMA table_info({table});"))
                        for r in res_cols.all():
                            columns.append({"name": r[1], "type": r[2]})
                    else:  # Postgres
                        res_cols = await conn.execute(text(
                            f"SELECT column_name, data_type FROM information_schema.columns "
                            f"WHERE table_schema = 'itciot' AND table_name='{table}';"
                        ))
                        for r in res_cols.all():
                            columns.append({"name": r[0], "type": r[1]})
                            
                    # Skip retrieving sample rows and row counts to avoid asyncpg transaction aborts
                    # on views or restricted tables. (Speeds up boot time significantly!)
                    sample_rows = []
                    row_count = 0
                        
                    tables.append({
                        "name": table,
                        "columns": columns,
                        "samples": sample_rows,
                        "row_count": row_count
                    })
            return {"tables": tables}
        except Exception as e:
            logger.error(f"Failed to extract schema: {e}")
            raise e


class SemanticLayer:
    """
    Automatically generates human-readable descriptions for tables and columns
    using LLM analysis of sample data and naming patterns.
    Enriches schema with business context.
    """
    
    def __init__(self, db_connector):
        self.db = db_connector
        self.cache = {}  # Cache generated descriptions
    
    async def enrich_schema(self, schema: Dict) -> Dict:
        """
        Enrich schema with auto-generated descriptions for tables and columns.
        """
        enriched_schema = {"tables": []}
        
        for table in schema.get("tables", []):
            table_name = table.get("name")
            
            # Check cache first
            if table_name in self.cache:
                enriched_schema["tables"].append(self.cache[table_name])
                continue
            
            # Generate description for table
            table_desc = await self._generate_table_description(table)
            
            # Generate descriptions for columns
            enriched_columns = []
            for col in table.get("columns", []):
                col_name = col.get("name")
                col_desc = self._generate_column_description(
                    col_name, 
                    col.get("type"),
                    table.get("samples", [])
                )
                synonyms = self.get_column_synonyms(col_name)
                enriched_columns.append({
                    **col,
                    "description": col_desc,
                    "business_name": self._to_business_name(col_name),
                    "synonyms": synonyms
                })
            
            enriched_table = {
                **table,
                "description": table_desc,
                "columns": enriched_columns,
                "categorical_values": await self._fetch_categorical_values(table_name, table.get("columns", []))
            }
            
            self.cache[table_name] = enriched_table
            enriched_schema["tables"].append(enriched_table)
        
        return enriched_schema
    
    async def _fetch_categorical_values(self, table_name: str, columns: List[Dict]) -> List[str]:
        """Fetch distinct values for text columns that might be categorical."""
        categorical_vals = []
        for col in columns:
            col_type = col.get("type", "").lower()
            original_col_name = col.get("name", "")
            col_name = original_col_name.lower()
            if "char" in col_type or "text" in col_type or "string" in col_type:
                # Exclude columns that are likely unique IDs or timestamps
                if "id" in col_name and not col_name.endswith("_id"):
                    continue
                if col_name in ["created_at", "updated_at", "timestamp"]:
                    continue
                try:
                    prefix = "itciot." if "postgres" in self.db.db_url else ""
                    query = f'SELECT DISTINCT "{original_col_name}" FROM {prefix}{table_name} WHERE "{original_col_name}" IS NOT NULL LIMIT 50'
                    res = await self.db.execute_query(query)
                    for row in res.get("rows", []):
                        val = row.get(col.get("name"))
                        if val and isinstance(val, str) and len(val) > 2:
                            categorical_vals.append(val)
                except Exception as e:
                    logger.debug(f"Failed to fetch categorical values for {table_name}.{col_name}: {e}")
        return list(set(categorical_vals))

    async def _generate_table_description(self, table: Dict) -> str:
        """
        Generate a business-friendly table description programmatically.
        """
        table_name = table.get("name")
        columns = [c.get("name") for c in table.get("columns", [])]
        
        # 1. Check for manual user-provided descriptions first
        try:
            import json, os
            desc_file = os.path.join("config", "table_descriptions.json")
            if os.path.exists(desc_file):
                with open(desc_file, "r") as f:
                    manual_descs = json.load(f)
                    if table_name in manual_descs:
                        return manual_descs[table_name]
        except Exception as e:
            logger.warning(f"Failed to load manual descriptions: {e}")
        
        # 2. Quick heuristic descriptions for common patterns
        name_lower = table_name.lower()
        if "ega" in name_lower:
            return "Excess Give Away (EGA) details per machine and variant"
        elif "oee" in name_lower:
            return "Overall Equipment Effectiveness metrics per machine"
        elif "wastage" in name_lower or "waste" in name_lower:
            return "Production wastage and scrap records with reasons"
        elif "employee" in name_lower or "staff" in name_lower:
            return "Employee list with roles, certifications and shift assignments"
        elif "feeder" in name_lower and "stat" in name_lower:
            return "Feeder cycle statistics and amplitude performance data"
        elif "feedback" in name_lower or "production" in name_lower:
            return f"Production feedback and performance data tracking actual vs target metrics"
        elif "silo" in name_lower or "inventory" in name_lower:
            return f"Inventory levels and stock tracking for raw materials"
        elif "meter" in name_lower or "power" in name_lower or "electric" in name_lower:
            return f"Energy consumption and power usage monitoring"
        elif "humidity" in name_lower or "temperature" in name_lower:
            return f"Environmental conditions monitoring (temperature, humidity, etc.)"
        elif "error" in name_lower or "log" in name_lower or "event" in name_lower:
            return f"System events, errors, and operational logs"
        elif "setting" in name_lower or "config" in name_lower:
            return f"Machine parameters, limits, and golden threshold settings"
        elif "assign" in name_lower or "schedule" in name_lower:
            return f"Staff scheduling, shifts, and team assignments"
        elif "cert" in name_lower or "train" in name_lower:
            return f"Operator certifications, skills, and training levels"
        elif "order" in name_lower or "client" in name_lower or "sale" in name_lower:
            return f"Sales orders, client specifications, and shipment records"
            
        return f"Data table containing {', '.join(columns[:3])} and related industrial information"
    
    def _generate_column_description(self, col_name: str, col_type: str, samples: List[Dict]) -> str:
        """
        Generate human-readable column description based on name and sample data.
        """
        name_lower = col_name.lower()
        
        # Common patterns
        if name_lower in ["id", "uuid", "guid"]:
            return "Unique identifier"
        elif "created" in name_lower or "timestamp" in name_lower or "date" in name_lower:
            return "Timestamp of record creation"
        elif "updated" in name_lower or "modified" in name_lower:
            return "Last modification timestamp"
        elif "actual" in name_lower and "weight" in name_lower:
            return "Actual measured weight of produced item"
        elif "target" in name_lower and "weight" in name_lower:
            return "Target/expected weight specification"
        elif "actual" in name_lower and "speed" in name_lower:
            return "Actual production line speed"
        elif "target" in name_lower and "speed" in name_lower:
            return "Target/optimal production speed"
        elif "variant" in name_lower or "product" in name_lower:
            return "Product variant or SKU identifier"
        elif "shift" in name_lower:
            return "Work shift identifier (morning/afternoon/night)"
        elif "machine" in name_lower or "line" in name_lower:
            return "Production line or machine identifier"
        elif "cost" in name_lower:
            return "Monetary cost value"
        elif "level" in name_lower:
            return "Quantity or level measurement"
        elif "percent" in name_lower or "pct" in name_lower:
            return "Percentage value"
        elif "count" in name_lower or "total" in name_lower:
            return "Count or total quantity"
        elif "error" in name_lower or "status" in name_lower:
            return "Status or error code"
        
        # Analyze sample data
        if samples and col_name in samples[0]:
            sample_val = samples[0][col_name]
            if isinstance(sample_val, (int, float)):
                return f"Numeric measurement ({col_type})"
            elif isinstance(sample_val, str):
                return f"Text/categorical field ({col_type})"
        
        return f"Data field of type {col_type}"
    
    def _to_business_name(self, col_name: str) -> str:
        """
        Convert technical column name to business-friendly name.
        Example: actual_weight -> Actual Weight
        """
        # Replace underscores with spaces and title case
        business_name = col_name.replace("_", " ").title()
        
        # Handle common abbreviations
        replacements = {
            "Id": "ID",
            "Uuid": "UUID",
            "Ega": "EGA",
            "Oee": "OEE",
            "Kg": "KG",
            "Pct": "Percent",
            "Qty": "Quantity",
            "Avg": "Average",
            "Min": "Minimum",
            "Max": "Maximum",
            "Std": "Standard",
            "Temp": "Temperature"
        }
        
        for old, new in replacements.items():
            business_name = business_name.replace(old, new)
        
        return business_name
    
    def get_column_synonyms(self, col_name: str) -> List[str]:
        """
        Return common synonyms for a column name to improve query understanding.
        """
        synonyms_map = {
            "actual_weight": ["real weight", "measured weight", "final weight", "produced weight"],
            "target_weight": ["expected weight", "goal weight", "spec weight"],
            "actual_speed": ["real speed", "current speed", "production rate"],
            "variant": ["product", "sku", "item", "product type"],
            "shift": ["work shift", "shift time", "shift period"],
            "created_at": ["timestamp", "date", "time", "created date"],
            "cost": ["price", "expense", "charge"],
            "level_kg": ["inventory", "stock", "quantity"],
            "ega_percent": ["excess giveaway", "give away percent", "extra weight", "overweight percent"],
            "oee_percent": ["overall efficiency", "equipment effectiveness", "oee score"],
            "unix_timestamp": ["timestamp", "time", "date", "recorded at", "log time"],
            "machine_id": ["machine", "loop", "weigher", "line id", "machine name"],
            "grammage": ["weight", "pack size", "gram", "grams", "g", "package weight"],
            "topic": ["feeder id", "feeder name", "machine topic"]
        }
        
        return synonyms_map.get(col_name.lower(), [])

    def invalidate_cache(self, table_name: str = None):
        if table_name:
            self.cache.pop(table_name, None)
        else:
            self.cache.clear()
        logger.info(f"Semantic cache invalidated: {table_name or 'all'}")
"""
Memory & Caching Layer - Implements Semantic Cache and Unified Conversation Manager
"""

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
                from core_engine import OllamaEmbeddingFunction
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

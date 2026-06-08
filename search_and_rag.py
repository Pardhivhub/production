# search_and_rag.py
import logging
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple
import requests
import chromadb
from chromadb import EmbeddingFunction
from backend.config import settings

logger = logging.getLogger(__name__)

# =====================================================================
# 1. Ollama Embedding Function (formerly embedder.py)
# =====================================================================

class OllamaEmbeddingFunction(EmbeddingFunction):
    """Callable that sends texts to an Ollama server and returns embeddings.
    Inherits from chromadb.EmbeddingFunction to avoid validation issues.
    """
    def __init__(self, model_name: str, url: str):
        self.model_name = model_name
        # Automatically redirect legacy /api/embeddings to the modern and robust /api/embed
        if url.endswith("/api/embeddings"):
            self.url = url.replace("/api/embeddings", "/api/embed")
        else:
            self.url = url

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Map the input to a list of strings and truncate to 1000 chars to fit context limit
        inputs = [text[:1000] for text in input]
        try:
            # Send batch request to modern /api/embed
            response = requests.post(
                self.url,
                json={"model": self.model_name, "input": inputs},
                timeout=180,
            )
            response.raise_for_status()
            return response.json()["embeddings"]
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}. Falling back to single-item fallback.")
            
            # Fallback to single-item processing or legacy endpoint just in case
            embeddings: List[List[float]] = []
            for text in inputs:
                try:
                    response = requests.post(
                        self.url,
                        json={"model": self.model_name, "input": text},
                        timeout=30,
                    )
                    response.raise_for_status()
                    res_json = response.json()
                    if "embeddings" in res_json:
                        embeddings.append(res_json["embeddings"][0])
                    else:
                        embeddings.append(res_json["embedding"])
                except Exception as ex:
                    logger.error(f"Fallback failed for text (len={len(text)}): {ex}")
                    embeddings.append([0.0] * 384)
            return embeddings


# =====================================================================
# 2. Schema Embedder (formerly embedder.py)
# =====================================================================

class SchemaEmbedder:
    """Embeds each table (its name, description and column list) into a ChromaDB collection.
    The collection is persisted under ``settings.CHROMA_PERSIST_DIR`` so it survives process restarts.
    """
    def __init__(self):
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self.ef = OllamaEmbeddingFunction(
            model_name="all-minilm:latest",
            url=f"{settings.OLLAMA_BASE_URL}/api/embeddings",
        )
        
        # Safe collection retrieval with automatic conflict recovery
        coll_name = "schema_embeddings"
        try:
            self.collection = self.client.get_or_create_collection(
                name=coll_name,
                embedding_function=self.ef,
            )
        except Exception as e:
            logger.warning(f"Embedding function conflict/error for collection '{coll_name}': {e}. Recreating...")
            try:
                self.client.delete_collection(coll_name)
            except Exception:
                pass
            self.collection = self.client.create_collection(
                name=coll_name,
                embedding_function=self.ef,
            )

    def _table_to_text(self, table: Dict) -> str:
        """Flatten a table dict into a single descriptive string for embedding.
        Expected keys on *table*: ``name``, ``description`` (optional), ``columns`` (list of dicts with ``name``, ``description``, ``synonyms``), ``samples``.
        """
        name = table.get("name", "")
        description = table.get("description", "")

        # Create a more detailed column string, using the rich data from the Semantic Layer
        col_descriptions = []
        for c in table.get("columns", []):
            col_name = c.get("name", "")
            col_desc = c.get("description", "")
            col_synonyms = c.get("synonyms", [])
            
            desc_str = f"{col_name}"
            if col_desc and col_desc != "Unique identifier": # Don't need to state the obvious
                desc_str += f" ({col_desc})"
            if col_synonyms:
                desc_str += f" (also known as: {', '.join(col_synonyms)})"
            col_descriptions.append(desc_str)
        cols = ". ".join(col_descriptions)
        
        # Include sample values for better semantic matching
        samples = table.get("samples", [])
        sample_str = ""
        if samples:
            sample_str = f" Sample values: {str(samples[0])}"
        
        return f"Table: {name}. Description: {description}. Columns: {cols}.{sample_str}"

    def embed_schema(self, schema: Dict):
        """Index all tables from a ``schema`` dict.
        ``schema`` must contain a top‑level ``tables`` list where each entry is a dict as described above.
        """
        tables = schema.get("tables", [])
        if not tables:
            logger.warning("No tables found to embed.")
            return

        ids, documents = [], []
        for tbl in tables:
            ids.append(tbl.get("name", ""))
            documents.append(self._table_to_text(tbl))

        logger.info("Embedding %d tables into ChromaDB…", len(ids))
        self.collection.upsert(ids=ids, documents=documents)
        logger.info("Schema embedding complete.")

    def query(self, user_question: str, top_k: int = 3) -> List[str]:
        """Return the *names* of the most relevant tables for ``user_question``.
        Uses the same embedding function for the query text.
        """
        q_emb = self.ef([user_question])
        results = self.collection.query(query_embeddings=q_emb, n_results=top_k)
        return results["ids"][0] if results.get("ids") else []
    
    def query_with_scores(self, user_question: str, top_k: int = 5, distance_threshold: float = 1.2) -> List[tuple]:
        """Return table names with their distance scores, filtered by threshold.
        ChromaDB returns L2 distance — lower is better.
        """
        q_emb = self.ef([user_question])
        results = self.collection.query(
            query_embeddings=q_emb, 
            n_results=top_k,
            include=["distances"]
        )
        
        if not results.get("ids") or not results.get("distances"):
            return []
        
        ids = results["ids"][0]
        distances = results["distances"][0]
        
        # Filter by distance threshold
        filtered = [(id_, dist) for id_, dist in zip(ids, distances) if dist < distance_threshold]
        logger.info(f"Query returned {len(filtered)}/{len(ids)} tables after score filtering (threshold={distance_threshold})")
        
        return filtered


# =====================================================================
# 3. RAG Explorer (formerly rag_explorer.py)
# =====================================================================

class RAGExplorer:
    """
    Retrieval-Augmented Generation (RAG) Document Explorer.
    Indexes text files under a directory and allows semantic query retrieval.
    Completely unified to use local Ollama embeddings to boot instantly and run lightweight.
    """
    def __init__(self, collection_name: str = "rag_docs", persist_dir: str = "./chroma_rag"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Reuse Ollama embedding function (which inherits from chromadb.EmbeddingFunction)
        self.ef = OllamaEmbeddingFunction(
            model_name="all-minilm:latest",
            url=f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        )
        
        # Safe collection retrieval with automatic conflict recovery
        try:
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.ef
            )
        except Exception as e:
            logger.warning(f"Embedding function conflict/error for collection '{collection_name}': {e}. Recreating...")
            try:
                self.client.delete_collection(collection_name)
            except Exception:
                pass
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.ef
            )
        logger.info(f"RAGExplorer initialized using Ollama embeddings (persisted to {persist_dir})")

    def _load_documents(self, source_dir: str) -> List[Tuple[str, str]]:
        """Read all txt and md files from directory."""
        docs = []
        base = Path(source_dir).expanduser()
        if not base.exists():
            logger.warning(f"RAG document source directory '{source_dir}' does not exist.")
            return docs
            
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".txt", ".md"}:
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        docs.append((str(path), content))
                except Exception as e:
                    logger.warning(f"Failed to read file {path}: {e}")
        logger.info(f"Loaded {len(docs)} files from {source_dir}")
        return docs

    def index_folder(self, source_dir: str):
        """Index a folder containing textual knowledge documents."""
        docs = self._load_documents(source_dir)
        if not docs:
            logger.warning("No documents found to index.")
            return
            
        ids = [doc[0] for doc in docs]
        texts = [doc[1] for doc in docs]
        
        self.collection.upsert(
            ids=ids,
            documents=texts
        )
        logger.info(f"Indexed {len(ids)} documents into Chroma collection.")

    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[str, str]]:
        """Retrieve most semantically relevant documents for the query."""
        try:
            # Query using the embedding function
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k
            )
            hits = []
            if results and results.get("ids") and results["ids"][0]:
                for doc_id, doc_text in zip(results["ids"][0], results["documents"][0]):
                    hits.append((doc_id, doc_text))
            return hits
        except Exception as e:
            logger.error(f"RAG retrieval failed: {e}")
            return []


class PromptRAG:
    """
    RAG utility to index and retrieve rules and worked examples dynamically for SQL generation.
    """
    def __init__(self, persist_dir: str = "./chroma_prompt_rag"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.ef = OllamaEmbeddingFunction(
            model_name="all-minilm:latest",
            url=f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        )
        try:
            self.rules_collection = self.client.get_or_create_collection(
                name="sql_rules",
                embedding_function=self.ef
            )
            self.examples_collection = self.client.get_or_create_collection(
                name="sql_examples",
                embedding_function=self.ef
            )
        except Exception as e:
            logger.warning(f"Chroma DB recreate error for PromptRAG: {e}")
            try:
                self.client.delete_collection("sql_rules")
                self.client.delete_collection("sql_examples")
            except Exception:
                pass
            self.rules_collection = self.client.create_collection(name="sql_rules", embedding_function=self.ef)
            self.examples_collection = self.client.create_collection(name="sql_examples", embedding_function=self.ef)
        logger.info("PromptRAG initialized successfully.")

    def index_prompts(self, rules_dir: str, examples_dir: str):
        """Read all rule and example text files and index them in ChromaDB."""
        # Index rules
        r_dir = Path(rules_dir)
        if r_dir.exists():
            ids, docs = [], []
            for path in r_dir.glob("*.txt"):
                ids.append(path.name)
                docs.append(path.read_text(encoding="utf-8").strip())
            if ids:
                self.rules_collection.upsert(ids=ids, documents=docs)
                logger.info(f"Indexed {len(ids)} rules into prompt RAG.")
                
        # Index examples
        e_dir = Path(examples_dir)
        if e_dir.exists():
            ids, docs = [], []
            for path in e_dir.glob("*.txt"):
                ids.append(path.name)
                docs.append(path.read_text(encoding="utf-8").strip())
            if ids:
                self.examples_collection.upsert(ids=ids, documents=docs)
                logger.info(f"Indexed {len(ids)} examples into prompt RAG.")

    def get_relevant_prompt_context(self, query: str, top_rules: int = 4, top_examples: int = 3) -> Tuple[str, str]:
        """Retrieve the top most semantically relevant rules and worked examples for the query."""
        # Query rules
        try:
            r_res = self.rules_collection.query(query_texts=[query], n_results=top_rules)
            ret_rules = r_res["documents"][0] if r_res and r_res.get("documents") else []
        except Exception as e:
            logger.error(f"Failed to query rules: {e}")
            ret_rules = []
            
        # Query examples
        try:
            e_res = self.examples_collection.query(query_texts=[query], n_results=top_examples)
            ret_examples = e_res["documents"][0] if e_res and e_res.get("documents") else []
        except Exception as e:
            logger.error(f"Failed to query examples: {e}")
            ret_examples = []
            
        rules_str = "\n\n".join(ret_rules)
        examples_str = "\n\n".join(ret_examples)
        return rules_str, examples_str



# =====================================================================
# 4. Table Selector (formerly table_selector.py)
# =====================================================================

def _load_exclude_words() -> set:
    try:
        path = Path(__file__).parent / "config" / "kpi_catalog.json"
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
        return set(catalog.get("exclude_column_words", []))
    except Exception:
        # Fallback hardcoded list
        return {
            "id", "uuid", "created_at", "updated_at", "timestamp",
            "time", "date", "start_time", "end_time", "shift",
            "name", "role", "value"
        }

def _load_table_rules() -> tuple:
    try:
        rules_path = Path(__file__).parent / "prompts" / "table_rules.json"
        if rules_path.exists():
            with open(rules_path, "r") as f:
                data = json.load(f)
                return (
                    set(data.get("PRODUCTION_TABLES", [])),
                    set(data.get("NON_PRODUCTION_TABLES", [])),
                    set(data.get("JOIN_TABLES", [])),
                )
    except Exception as e:
        logger.error(f"Failed to load table_rules.json in table_selector: {e}")
    # Fallback to defaults
    return (
        {"ega_details_data", "oee_details_data", "production_speed_details_data",
         "wastage_records", "gsm_usage_details"},
        {"employees_list", "shift_assignments"},
        {"machines", "gmiiot_plants", "gmiiot_lines", "flavours", "wastage_reasons", "recipes"},
    )

PRODUCTION_TABLES, NON_PRODUCTION_TABLES, JOIN_TABLES = _load_table_rules()


class TableSelector:
    """
    Fully schema-driven hybrid table selector.
    Zero hardcoded table names — works automatically when new tables are added.

    Scoring priority (highest wins):
      10 — exact column name mentioned in query
       9 — table confirmed by kpi_engine matched_tables
       8 — table name or part directly in query
       6 — synonym / description word match
       5 — vector semantic match (strong, distance < 0.8)
       3 — vector semantic match (weak, distance 0.8–1.2)
       0 — no match
    """

    def __init__(self, schema: Dict):
        self.schema = schema
        self.embedder = SchemaEmbedder()
        self.embedder.embed_schema(schema)

        # Build all indexes automatically from schema — no hardcoding
        self._col_to_tables: Dict[str, List[str]] = {}   # column_name → [table_names]
        self._word_to_tables: Dict[str, List[str]] = {}  # word/synonym → [table_names]
        self._table_names: Set[str] = set()
        self._build_indexes()

    def _build_indexes(self):
        """
        Automatically index every table, column, description word, and synonym.
        Called on init. Call refresh_schema() when a new table is added.
        """
        self._col_to_tables = {}
        self._word_to_tables = {}
        self._table_names = set()

        for table in self.schema.get("tables", []):
            t_name = table.get("name", "").lower()
            self._table_names.add(t_name)

            # Index table name parts (e.g. "ega_details_data" → ["ega","details","data"])
            for part in re.split(r"[_\-\s]", t_name):
                if len(part) > 2:
                    self._word_to_tables.setdefault(part, []).append(t_name)

            # Index table description words
            for word in table.get("description", "").lower().split():
                if len(word) > 3:
                    self._word_to_tables.setdefault(word, []).append(t_name)
                    
            # Index categorical data values fetched from db
            for val in table.get("categorical_values", []):
                for word in val.lower().split():
                    # keep >2 length words, strip non-alphanumeric
                    word = re.sub(r"[^a-z0-9]", "", word)
                    if len(word) > 2:
                        self._word_to_tables.setdefault(word, []).append(t_name)

            # Index every column
            for col in table.get("columns", []):
                col_name = col.get("name", "").lower()

                # Exact column name → table mapping
                self._col_to_tables.setdefault(col_name, []).append(t_name)

                # Column name parts
                for part in re.split(r"[_\-\s]", col_name):
                    if len(part) > 2:
                        self._word_to_tables.setdefault(part, []).append(t_name)

                # Column description words
                for word in col.get("description", "").lower().split():
                    if len(word) > 3:
                        self._word_to_tables.setdefault(word, []).append(t_name)

                # Column synonyms from semantic layer
                for syn in col.get("synonyms", []):
                    for sword in syn.lower().split():
                        if len(sword) > 3:
                            self._word_to_tables.setdefault(sword, []).append(t_name)

                # Business name words
                for word in col.get("business_name", "").lower().split():
                    if len(word) > 3:
                        self._word_to_tables.setdefault(word, []).append(t_name)

        logger.info(
            f"TableSelector index built: {len(self._table_names)} tables, "
            f"{len(self._col_to_tables)} columns, "
            f"{len(self._word_to_tables)} word mappings"
        )

    def refresh_schema(self, new_schema: Dict):
        """
        Call this when a new table is added to the database.
        Re-indexes everything and re-embeds into ChromaDB automatically.
        No code changes needed anywhere else.
        """
        logger.info("Refreshing TableSelector schema index...")
        self.schema = new_schema
        self._build_indexes()
        self.embedder.embed_schema(new_schema)
        logger.info("TableSelector schema refresh complete.")

    def select_relevant_tables(
        self,
        user_question: str,
        top_k: int = 5,
        distance_threshold: float = 1.2,
        kpi_matched_tables: List[str] = None
    ) -> Dict:
        """
        Returns {tables: [full table objects]} for the highest-scoring matches.

        kpi_matched_tables: pass matched_tables from kpi_engine.compile_domain_hints()
        — these get score=9 automatically, skipping all other logic for them.
        """
        scores: Dict[str, float] = {}

        q_lower = user_question.lower()
        q_clean = re.sub(r"[^a-z0-9\s_]", " ", q_lower)
        words = set(q_clean.split())

        # Also add singularized versions of words
        expanded_words = set(words)
        for w in words:
            if w.endswith("s") and len(w) > 3:
                expanded_words.add(w[:-1])
            if w.endswith("es") and len(w) > 4:
                expanded_words.add(w[:-2])
            if w.endswith("ing") and len(w) > 5:
                expanded_words.add(w[:-3])

        def add_score(table: str, points: float, reason: str):
            t = table.lower()
            if t in self._table_names:
                prev = scores.get(t, 0)
                scores[t] = max(prev, points)  # take highest signal, don't double-count
                logger.debug(f"  Score {t}: {prev} → {scores[t]} ({reason})")

        # --- Signal 1: KPI engine already identified these (score=15) ---
        if kpi_matched_tables:
            for t in kpi_matched_tables:
                add_score(t, 15.0, "kpi_engine_confirmed")

        # --- Signal 2: Exact column name match in query (score=10) ---
        EXCLUDE_COLUMN_EXACT = _load_exclude_words()
        for word in expanded_words:
            if word in EXCLUDE_COLUMN_EXACT:
                continue
            if word in self._col_to_tables:
                for t in self._col_to_tables[word]:
                    add_score(t, 10.0, f"exact_column_match:{word}")

        # --- Signal 3: Table name parts directly in query (score=8) ---
        for t_name in self._table_names:
            parts = [p for p in re.split(r"[_\-\s]", t_name) if len(p) > 2]
            if any(p in expanded_words for p in parts):
                add_score(t_name, 8.0, f"table_name_match:{t_name}")
            # Also check if full table name substring in query
            if t_name.replace("_", " ") in q_clean:
                add_score(t_name, 8.0, f"table_name_substring:{t_name}")

        # --- Signal 4: Word/synonym/description match (score=6) ---
        for word in expanded_words:
            if len(word) < 3 or word in EXCLUDE_COLUMN_EXACT:
                continue
            if word in self._word_to_tables:
                for t in self._word_to_tables[word]:
                    add_score(t, 6.0, f"word_match:{word}")

        # --- Signal 5: Vector semantic match ---
        try:
            scored_vector = self.embedder.query_with_scores(
                user_question, top_k=top_k, distance_threshold=distance_threshold
            )
            if not scored_vector:
                # Fallback: take top 2 regardless of threshold
                fallback = self.embedder.query(user_question, top_k=2)
                for t in fallback:
                    add_score(t, 2.0, "vector_fallback")
            else:
                for t_name, dist in scored_vector:
                    # Convert distance to score: closer = higher score
                    if dist < 0.6:
                        vscore = 5.0
                    elif dist < 0.8:
                        vscore = 4.0
                    elif dist < 1.0:
                        vscore = 3.0
                    else:
                        vscore = 2.0
                    add_score(t_name, vscore, f"vector_dist:{dist:.3f}")
        except Exception as e:
            logger.error(f"Vector query failed: {e}")

        # --- Cap / remove non-production config/metadata tables ---
        # JOIN_TABLES (gmiiot_plants, gmiiot_lines, machines) are NEVER suppressed —
        # they are dimension tables required for JOIN queries.
        production_max_score = max(
            (scores.get(t, 0) for t in PRODUCTION_TABLES if t in scores), default=0
        )
        for table_name in list(scores.keys()):
            # Never suppress join/dimension tables — they are needed for JOIN queries
            if table_name in JOIN_TABLES:
                logger.debug(f"Kept join table {table_name} (protected from suppression)")
                continue
            if table_name in NON_PRODUCTION_TABLES:
                if production_max_score >= 6:
                    # A real production table is already answering — drop config tables entirely
                    scores[table_name] = 0
                    logger.debug(f"Suppressed non-production table {table_name} (production score={production_max_score})")
                else:
                    # No strong production match — cap config tables to avoid false positives
                    scores[table_name] = min(scores[table_name], 3.0)
                    logger.debug(f"Capped non-production table {table_name} to 3")

        # --- Cap irrelevant tables when KPI engine identified the right ones ---
        if kpi_matched_tables:
            kpi_set = {t.lower() for t in kpi_matched_tables}
            for table_name in list(scores.keys()):
                if table_name not in kpi_set:
                    if scores[table_name] <= 6 and table_name in [
                        "shift_assignments", "employees_list", "feeder_metadata"
                    ]:
                        scores[table_name] = min(scores[table_name], 2.0)
                        logger.debug(f"Capped irrelevant table {table_name} score to 2")

        # Remove zero-scored tables entirely
        scores = {k: v for k, v in scores.items() if v > 0}

        # --- Final ranking ---
        if not scores:
            # Nothing matched at all — return top 2 by vector as last resort
            logger.warning("No tables matched — using pure vector fallback top 2")
            fallback = self.embedder.query(user_question, top_k=2)
            selected = [t for t in self.schema.get("tables", []) if t["name"].lower() in fallback]
            return {"tables": selected}

        # Sort by score descending, take top_k
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if ranked:
            top_score = ranked[0][1]
            # If we have a very strong match (>= 8), filter out weak semantic noise (<= 6)
            # EXCEPT for JOIN_TABLES, which should always be kept if they scored > 0
            if top_score >= 8:
                ranked = [
                    item for item in ranked 
                    if item[1] >= (top_score - 2) or item[0] in JOIN_TABLES
                ][:top_k]
            else:
                ranked = ranked[:top_k]
        
        final_names = {name for name, _ in ranked}

        selected = [
            t for t in self.schema.get("tables", [])
            if t["name"].lower() in final_names
        ]

        logger.info(
            "TableSelector scores: %s | Final: %s",
            [(n, f"{s:.1f}") for n, s in ranked],
            [t["name"] for t in selected]
        )

        return {
            "tables": selected,
            "scores": dict(ranked)
        }

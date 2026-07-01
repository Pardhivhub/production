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


RULE_DESCRIPTIONS = {
    "oee_details_data_1.txt": (
        "OEE details schema, columns run_duration, downtime_mins, good_bags, failed_bags, overlimit_count, target_speed, machine_id, loop_id, purpose, joins."
    ),
    "oee_details_data_2.txt": (
        "OEE calculations, availability formula, performance formula, quality formula, overall OEE formula, rules, AVG(oee) mistakes, division safety NULLIF."
    ),
    "ega_details_data_1.txt": (
        "EGA details schema, t_weight, theoretical_pack_weight, mean_weight, actual vs theoretical weight, giveaway loss, purpose, joins."
    ),
    "ega_details_data_2.txt": (
        "EGA giveaway formula, weight sums, AVG(ega_percent) mistakes, division safety NULLIF, outlier cleaning, weight outliers, RF weight buckets, target weight."
    ),
    "wastage_records_1.txt": (
        "Wastage records schema, columns wastage_kg, failed_bag_rejection, filled_bag_rejection, manual_rejection_kg, plant_id, line_id, machine_id, shift, flavour, grammage, purpose, joins."
    ),
    "wastage_records_2.txt": (
        "Wastage records JSON casting, wastage_breakdown, unaccounted_downtime_breakdown, shift comparisons, flavour ILIKE filtering, grammage format, production_start_time, production_end_time."
    ),
    "production_speed_details_1.txt": (
        "Production speed details schema, target_speed, speed_trend array, loop_id, machine_id, speed sensor active state, purpose, joins."
    ),
    "production_speed_details_2.txt": (
        "Speed trend jsonb array elements text unnesting, average speed, lateral join speed_trend, preset_master_uploader limits, speed calculations."
    ),
    "machines.txt": (
        "Machines master catalog, machine_id, machine_name PM1 PM2, type_id, device_id, machine name joins."
    ),
    "gmiiot_lines.txt": (
        "Lines master catalog, gmiiot_lines, loop_id, loop_name Line 1, plant_id, line joins."
    ),
    "gmiiot_plants.txt": (
        "Plants master catalog, gmiiot_plants, plant_id, plant_name Unit 1 Unit 2, multi-table joins, plant join path."
    ),
    "preset_master_uploader.txt": (
        "Presets master catalog, target_speed preset, SKU, grammage category, variant name Ridge Cut Flat Cut, machine_id, loop_id."
    ),
    "flavours.txt": (
        "Flavours master catalog, flavour_id, flavour_name Salted Cheese Chilli, variant_name, product flavour mappings."
    ),
    "global_rules.txt": (
        "Global SQL rules, Postgres syntax, case insensitive ILIKE, grouping date_trunc, division safety NULLIF, ranking ORDER BY LIMIT, temporal column selection, start_time vs production_start_time, outlier weight filtering."
    )
}

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
            try:
                self.client.delete_collection("sql_rules")
            except Exception:
                pass
            self.rules_collection = self.client.create_collection(
                name="sql_rules",
                embedding_function=self.ef
            )
            ids, docs, metadatas = [], [], []
            for path in r_dir.glob("*.md"):
                filename = path.name
                full_text = path.read_text(encoding="utf-8").strip()
                desc = full_text
                
                ids.append(filename)
                docs.append(desc)
                metadatas.append({"full_text": full_text})
            if ids:
                self.rules_collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
                logger.info(f"Indexed {len(ids)} rules into prompt RAG.")
                
        # Index examples
        e_dir = Path(examples_dir)
        if e_dir.exists():
            try:
                self.client.delete_collection("sql_examples")
            except Exception:
                pass
            self.examples_collection = self.client.create_collection(
                name="sql_examples",
                embedding_function=self.ef
            )
            ids, docs = [], []
            for path in e_dir.glob("*.md"):
                ids.append(path.name)
                docs.append(path.read_text(encoding="utf-8").strip())
            if ids:
                self.examples_collection.upsert(ids=ids, documents=docs)
                logger.info(f"Indexed {len(ids)} examples into prompt RAG.")

    def get_relevant_prompt_context(self, query: str, top_rules: int = None, top_examples: int = 3, score_threshold: float = None) -> Tuple[str, str, list]:
        """Retrieve the semantically relevant rules (filtered by score_threshold) and worked examples for the query."""
        if score_threshold is None:
            score_threshold = settings.RULE_SCORE_THRESHOLD

        # Query rules
        try:
            total_rules = max(10, self.rules_collection.count())
            r_res = self.rules_collection.query(
                query_texts=[query],
                n_results=total_rules,
                include=["metadatas", "distances"]
            )
            ret_rules = []
            rules_meta = []
            if r_res and r_res.get("metadatas") and r_res.get("distances"):
                metas = r_res["metadatas"][0]
                distances = r_res["distances"][0]
                ids = r_res["ids"][0]
                for meta, dist, r_id in zip(metas, distances, ids):
                    # Compute similarity score: L2 distance to cosine similarity
                    # ChromaDB returns squared L2 distance. Cosine similarity = 1 - distance / 2
                    score = 1.0 - (dist / 2.0)
                    logger.info(f"Rule evaluation: {r_id} | Distance: {dist:.4f} | Score: {score:.4f} (threshold: {score_threshold})")
                    if score >= score_threshold:
                        if meta and "full_text" in meta:
                            ret_rules.append(meta["full_text"])
                            rules_meta.append({"rule": r_id, "score": round(score, 4)})
            
            # Fallback in case no rules match threshold and a fallback count is requested
            if not ret_rules and top_rules:
                logger.info(f"No rules matched threshold {score_threshold}. Falling back to top {top_rules} rules.")
                r_res_fallback = self.rules_collection.query(query_texts=[query], n_results=top_rules, include=["metadatas", "distances"])
                if r_res_fallback and r_res_fallback.get("metadatas"):
                    metas = r_res_fallback["metadatas"][0]
                    distances = r_res_fallback.get("distances", [[0] * len(metas)])[0]
                    ids = r_res_fallback["ids"][0]
                    for meta, dist, r_id in zip(metas, distances, ids):
                        score = 1.0 - (dist / 2.0) if dist else 0.0
                        if meta and "full_text" in meta:
                            ret_rules.append(meta["full_text"])
                            rules_meta.append({"rule": r_id, "score": round(score, 4)})
        except Exception as e:
            logger.error(f"Failed to query rules: {e}")
            ret_rules = []
            rules_meta = []
            
        # Query examples
        try:
            e_res = self.examples_collection.query(query_texts=[query], n_results=top_examples)
            ret_examples = e_res["documents"][0] if e_res and e_res.get("documents") else []
        except Exception as e:
            logger.error(f"Failed to query examples: {e}")
            ret_examples = []
            
        rules_str = "\n\n".join(ret_rules)
        examples_str = "\n\n".join(ret_examples)
        return rules_str, examples_str, rules_meta



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

        STOP_WORDS = {
            "show", "me", "the", "total", "grouped", "group",
            "by", "each", "all", "get", "give", "for", "of"
        }
        q_lower = " ".join(w for w in user_question.lower().split() if w not in STOP_WORDS)
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
        ranked_names_order = [name for name, _ in ranked]
        table_by_name = {t["name"].lower(): t for t in self.schema.get("tables", [])}
        selected = [table_by_name[name] for name in ranked_names_order if name in table_by_name]

        logger.info(
            "TableSelector scores: %s | Final: %s",
            [(n, f"{s:.1f}") for n, s in ranked],
            [t["name"] for t in selected]
        )

        return {
            "tables": selected,
            "scores": dict(ranked)
        }

"""
KPI Engine, Router & Suggester - Manages manufacturing formulas, query classification, intent routing, and follow-up suggestions
"""
import logging
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from difflib import get_close_matches

logger = logging.getLogger(__name__)

TIME_COLUMN_MAP = {
    "oee_details_data": "start_time",
    "ega_details_data": "start_time",
    "production_speed_details_data": "start_time",
    "wastage_records": "production_start_time",
    "gsm_usage_details": "date",
}

FORMULAS_CATALOG = {
  "OEE": {
    "metric": "OEE_Availability",
    "aliases": ["oee", "oee performance", "machine performance", "overall equipment effectiveness", "overall efficiency", "equipment efficiency", "availability"],
    "type": "derived_kpi",
    "table": "oee_details_data",
    "formula": "((60.0 - SUM(downtime_mins)) / 60.0) * 100 per machine per hour",
    "query": "SELECT machine_id, machine_name, SUM(downtime_mins) AS total_downtime, ROUND(((COUNT(*)*60.0 - SUM(downtime_mins))/(COUNT(*)*60.0))*100::numeric, 2) AS availability_pct FROM oee_details_data GROUP BY machine_id, machine_name ORDER BY availability_pct DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"],
    "notes": "There is NO 'oee' column! Use downtime_mins for downtime and availability. good_bags and failed_bags for quality."
  },
  "EGA_percent": {
    "metric": "EGA_percent",
    "aliases": ["ega", "ega percent", "ega %", "ega_percentage", "excess give away percent", "extra give away percent", "excess give away %", "extra weight given away", "excess give away", "giveaway", "extra weight"],
    "type": "stored_kpi",
    "table": "ega_details_data",
    "formula": "AVG(ega_percent)",
    "query": "SELECT machine_id, machine_name, AVG(ega_percent) AS avg_ega FROM ega_details_data GROUP BY machine_id, machine_name ORDER BY avg_ega DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant", "grammage"],
    "notes": "ega_percent is a stored NUMERIC column per hourly row. Use AVG(ega_percent) when grouping by machine. grammage is NUMERIC like 10.5, 20, 43 without 'g' suffix."
  },
  "Wastage": {
    "metric": "Wastage",
    "aliases": ["wastage", "waste", "scrap", "material loss", "wastage kg"],
    "type": "stored_kpi",
    "table": "wastage_records",
    "formula": "SUM(wastage_kg)",
    "query": "SELECT machine_id, line_id, SUM(wastage_kg) AS total_wastage FROM wastage_records GROUP BY machine_id, line_id",
    "time_column": "production_start_time",
    "groupable_by": ["machine_id", "line_id", "shift", "grammage"],
    "filters": ["machine_id", "line_id", "shift"]
  },
  "Production_Speed": {
    "metric": "Production_Speed",
    "aliases": ["production speed", "speed", "actual speed", "machine speed", "avg speed", "bpm"],
    "type": "stored_kpi",
    "table": "production_speed_details_data",
    "formula": "AVG(unnest(production_speed_bpm))",
    "query": "SELECT machine_id, machine_name, ROUND(AVG(unnest_speed)::numeric,2) AS avg_speed_bpm FROM production_speed_details_data, unnest(production_speed_bpm) AS unnest_speed GROUP BY machine_id, machine_name ORDER BY avg_speed_bpm DESC",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "machine_name", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"],
    "notes": "production_speed_bpm is a NUMERIC ARRAY column. Use unnest(production_speed_bpm) to aggregate it. Do NOT use production_speed (it is a JSON text column)."
  }
}

RELATIONSHIPS_CATALOG = [
  {
    "from_table": "ega_details_data",
    "from_column": "machine_id",
    "to_table": "oee_details_data",
    "to_column": "machine_id",
    "type": "many-to-many",
    "description": "Link machine production data (EGA) with OEE metrics via machine_id"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "loop_id",
    "to_table": "oee_details_data",
    "to_column": "loop_id",
    "type": "many-to-many",
    "description": "Link production loops across EGA and OEE tables"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "grammage",
    "to_table": "oee_details_data",
    "to_column": "grammage",
    "type": "many-to-many",
    "description": "Link by SKU/grammage"
  },
  {
    "from_table": "ega_details_data",
    "from_column": "variant",
    "to_table": "oee_details_data",
    "to_column": "variant",
    "type": "many-to-many",
    "description": "Link product variant data between EGA and OEE"
  },
  {
    "from_table": "wastage_records",
    "from_column": "machine_id",
    "to_table": "ega_details_data",
    "to_column": "machine_id",
    "type": "many-to-many",
    "description": "Link wastage records to machine production data"
  },
  {
    "from_table": "wastage_records",
    "from_column": "line_id",
    "to_table": "ega_details_data",
    "to_column": "loop_id",
    "type": "many-to-many",
    "description": "Link production loop/line for wastage reporting"
  },
  {
    "from_table": "wastage_records",
    "from_column": "grammage",
    "to_table": "ega_details_data",
    "to_column": "grammage",
    "type": "many-to-many",
    "description": "Link wastage records to SKU/grammage of production"
  }
]

SHIFT_PATTERNS = {
  "morning shift": {
    "start": "06:00:00",
    "end": "14:00:00",
    "label": "Morning Shift",
    "aliases": ["morning", "morning shift", "shift 1", "first shift", "day shift"]
  },
  "afternoon shift": {
    "start": "14:00:00",
    "end": "22:00:00",
    "label": "Afternoon Shift",
    "aliases": ["afternoon", "afternoon shift", "shift 2", "second shift", "evening shift"]
  },
  "night shift": {
    "start": "22:00:00",
    "end": "06:00:00",
    "label": "Night Shift",
    "aliases": ["night", "night shift", "shift 3", "third shift", "overnight shift"]
  }
}


class KPIEngine:
    def __init__(self, schema_info: dict = None):
        self.schema_info = schema_info or {"tables": []}
        
        try:
            path = Path(__file__).parent / "config" / "kpi_catalog.json"
            with open(path, encoding="utf-8") as f:
                catalog = json.load(f)
            self.kpi_formulas = catalog.get("formulas", FORMULAS_CATALOG)
            self.relationships = catalog.get("relationships", RELATIONSHIPS_CATALOG)
            self.shift_patterns = catalog.get("shifts", SHIFT_PATTERNS)
        except Exception:
            self.kpi_formulas = FORMULAS_CATALOG
            self.relationships = RELATIONSHIPS_CATALOG
            self.shift_patterns = SHIFT_PATTERNS

    def compile_domain_hints(self, user_query: str) -> dict:
        q_lower = user_query.lower()
        hints = []
        corrections = {}
        matched_tables = set()

        # ── Machine synonym resolution ──────────────────────────────────
        machine_num_patterns = re.findall(
            r'(?:machine[\s\-]*(\d+)|weigher[\s\-]*(\d+)|machine\s*id[\s\-]*(\d+))',
            q_lower
        )
        machine_ids_mentioned = []
        for groups in machine_num_patterns:
            mid = next((g for g in groups if g), None)
            if mid:
                machine_ids_mentioned.append(int(mid))
        
        if machine_ids_mentioned:
            if len(machine_ids_mentioned) == 1:
                hints.append(
                    f"- MACHINE FILTER: User refers to machine #{machine_ids_mentioned[0]}. "
                    f"Use: machine_id = {machine_ids_mentioned[0]}"
                )
            else:
                ids_str = ", ".join(str(m) for m in machine_ids_mentioned)
                in_clause = ", ".join(str(m) for m in machine_ids_mentioned)
                hints.append(
                    f"- COMPARE MACHINES RULE: User wants to compare machines {ids_str} side by side. "
                    f"MANDATORY: Use machine_id IN ({in_clause}) WITH GROUP BY machine_id, machine_name. "
                    f"Include machine_id AND machine_name in SELECT. "
                    f"Result MUST have {len(machine_ids_mentioned)} rows — one per machine. "
                    f"NEVER omit GROUP BY and return a single combined total row."
                )
        
        compare_keywords = ["compare", " vs ", " vs.", " versus ", " and machine ", " and weigher "]
        if any(kw in q_lower for kw in compare_keywords) and len(machine_ids_mentioned) >= 2:
            hints.append(
                "- COMPARISON INTENT DETECTED: User is comparing multiple machines. "
                "Each machine MUST be its own row. Always add GROUP BY machine_id, machine_name. "
                "Do NOT aggregate all machines into a single total row."
            )

        # ── Table routing by keyword ────────────────────────────────────
        if any(w in q_lower for w in ["ega", "giveaway", "give away", "excess give away", "extra weight"]):
            matched_tables.add("ega_details_data")
        if any(w in q_lower for w in ["oee", "downtime", "availability", "performance", "quality", "good bags", "failed bags"]):
            matched_tables.add("oee_details_data")
        if any(w in q_lower for w in ["speed", "bpm", "production speed"]):
            matched_tables.add("production_speed_details_data")
        if any(w in q_lower for w in ["wastage", "waste", "scrap"]):
            matched_tables.add("wastage_records")

        # 1. Math aggregate and catalog metric detection
        for kpi_id, meta in self.kpi_formulas.items():
            aliases = meta.get("aliases", [kpi_id.replace("_", " ").lower()])
            if any(alias in q_lower for alias in aliases):
                metric = meta.get("metric")
                table = meta.get("table")
                formula = meta.get("formula")
                query_example = meta.get("query")
                notes = meta.get("notes", "")
                
                hint_text = (
                    f"- KPI METRIC DETECTED ({metric.upper()}): Use table '{table}', "
                    f"aggregate with formula: `{formula}`. "
                    f"Example: `{query_example}`"
                )
                if notes:
                    hint_text += f" NOTE: {notes}"
                hints.append(hint_text)
                if table:
                    matched_tables.add(table.split(".")[-1])

        # 2. Shift Range Processing
        for shift_name, shift_data in self.shift_patterns.items():
            start_t = shift_data["start"]
            end_t = shift_data["end"]
            label = shift_data["label"]
            aliases = shift_data.get("aliases", [shift_name])
            if any(alias in q_lower for alias in aliases):
                time_col = "start_time"
                for t in matched_tables:
                    if t in TIME_COLUMN_MAP:
                        time_col = TIME_COLUMN_MAP[t]
                        break

                if label == "Night Shift":
                    time_filter = (
                        f"({time_col}::time >= '{start_t}' "
                        f"OR {time_col}::time < '{end_t}')"
                    )
                else:
                    time_filter = (
                        f"{time_col}::time >= '{start_t}' "
                        f"AND {time_col}::time < '{end_t}'"
                    )

                hints.append(
                    f"- SHIFT FILTER ({label.upper()}): "
                    f"Do NOT join shift_assignments. "
                    f"Filter directly: WHERE {time_filter}"
                )

        # 3. Fuzzy Spelling & Column/Table Correction
        actual_columns = []
        column_to_table = {}
        for table_meta in self.schema_info.get("tables", []):
            table_name = table_meta.get("name", "")
            for col in table_meta.get("columns", []):
                col_name = col.get("name", "")
                actual_columns.append(col_name)
                column_to_table[col_name] = table_name

        EXCLUDE_FUZZY = {
            "find", "show", "list", "get", "each", "what", "where", "when", "with", "have",
            "mean", "name", "date", "time", "hour", "year", "month", "week", "day", "rate",
            "cost", "peak", "free", "data", "line", "type", "from", "info", "than", "alert",
            "total", "grouped", "group", "by", "all", "give", "for", "of", "the", "me"
        }

        words = re.findall(r"\b\w+\b", q_lower)
        for word in words:
            if len(word) < 4 or word in EXCLUDE_FUZZY:
                continue
            if any(word in col for col in actual_columns):
                continue
                
            matches = get_close_matches(word, actual_columns, n=1, cutoff=0.80)
            if matches and matches[0] != word:
                matched_col = matches[0]
                corrections[word] = matched_col
                target_tbl = column_to_table[matched_col]
                matched_tables.add(target_tbl)
                hints.append(
                    f"- FUZZY MATCH: The word '{word}' was mapped to the database column '{matched_col}' "
                    f"in table '{target_tbl}'."
                )

        # 4. Multi-Table Join Generation
        if len(matched_tables) > 1:
            for rel in self.relationships:
                from_t = rel["from_table"].split(".")[-1]
                to_t = rel["to_table"].split(".")[-1]
                if from_t in matched_tables and to_t in matched_tables:
                    hints.append(
                        f"- JOIN RELATIONSHIP DETECTED: To join '{from_t}' and '{to_t}', "
                        f"use: `JOIN {to_t} ON {from_t}.{rel['from_column']} = {to_t}.{rel['to_column']}` "
                        f"({rel['description']})."
                    )

        # 5. Counting and Filtering Rules
        counting_keywords = ["how many", "count", "total number", "number of"]
        listing_keywords = ["list all", "show all", "give me all", "display all", "get all"]
        filtering_keywords = ["where", "with", "having", ">", "<", "=", "above", "below", "greater", "less", "highest", "lowest", "maximum", "minimum", "best", "worst"]
        
        has_counting = any(kw in q_lower for kw in counting_keywords)
        has_listing = any(kw in q_lower for kw in listing_keywords)
        has_filtering = any(kw in q_lower for kw in filtering_keywords)
        
        if has_counting or has_listing:
            if has_filtering:
                hints.append(
                    "- COUNTING + FILTERING RULE: User wants both count AND details. "
                    "Return ALL matching rows with SELECT * or SELECT [columns] WHERE [condition]. "
                    "Do NOT use LIMIT. The explainer will count and list all items."
                )
            elif "only" in q_lower or "just" in q_lower:
                hints.append(
                    "- COUNT-ONLY RULE: User wants only the count. Use SELECT COUNT(*) or COUNT(DISTINCT column)."
                )
            else:
                hints.append(
                    "- TOTAL COUNT RULE: User wants to count all items. "
                    "Return ALL rows with SELECT * FROM table. The explainer will count and report the total."
                )
        
        if has_listing and has_filtering:
            hints.append(
                "- LISTING RULE: Return ALL matching rows without LIMIT. "
                "Include relevant columns for context (IDs, names, metrics). "
                "The explainer will state: 'There are X items with [condition]' and list all of them."
            )

        if has_filtering:
            hints.append(
                "- FILTERING/COMPARISON RULE: The user is asking to filter or find records matching a specific comparison "
                "(e.g., 'highest', 'lowest', 'greater than', 'above', 'below', '<', '>', '=', etc.). "
                "For 'highest' or 'lowest' queries, use ORDER BY with the metric column and LIMIT 1. "
                "For threshold comparisons, list the individual records/rows matching the filter condition, "
                "including relevant identifying columns (like machine_id, loop_id, variant, start_time/timestamp) "
                "and the metric column itself. Do NOT aggregate with AVG() or SUM() for the whole table when filtering. "
                "Example for 'highest ega': `SELECT machine_id, loop_id, variant, start_time, ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 AS ega_percent FROM ega_details_data ORDER BY ega_percent DESC LIMIT 1` "
                "Example for 'ega greater than 2.5': `SELECT machine_id, loop_id, variant, start_time, ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 AS ega_percent FROM ega_details_data WHERE ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100 > 2.5`"
            )

        # 6. Date/Time parsing for specific dates
        date_patterns = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', user_query)
        if date_patterns:
            time_col = "start_time"
            for t in matched_tables:
                if t in TIME_COLUMN_MAP:
                    time_col = TIME_COLUMN_MAP[t]
                    break
            
            for date_str in date_patterns:
                hints.append(
                    f"- PARSED TIME FILTER: {time_col}::date = '{date_str}'"
                )
                hints.append(
                    f"- DATE+GROUPBY RULE: Since a date filter is applied, ALWAYS use "
                    f"GROUP BY machine_id (and machine_name if selected) so each machine "
                    f"shows its daily aggregate, not just one hourly row."
                )
                break

        # 7. Grammage format normalization
        grammage_patterns = re.findall(r'\b(\d+(?:\.\d+)?)\s*(?:g\b|grams?\b|(?=\s+(?:ridge|flat|variant)))', q_lower, re.IGNORECASE)
        seen_grammage = set()
        for gram_val in grammage_patterns:
            try:
                gram_num = float(gram_val)
                if gram_num > 5 and gram_num < 500 and gram_num not in seen_grammage:
                    seen_grammage.add(gram_num)
                    hints.append(
                        f"- GRAMMAGE FORMAT: User mentioned '{gram_val}' grams. "
                        f"The grammage column is NUMERIC (stores numbers like 10.5, 20, 43, 85, 90, NOT text). "
                        f"Use: grammage = {gram_num} (as a NUMBER without quotes or 'g' suffix)"
                    )
                    break
            except ValueError:
                continue

        # 8. Availability semantic mapping
        if "availability" in q_lower or "available" in q_lower:
            if any(pattern in q_lower for pattern in ["100%", "100 percent", "full availability", "perfect availability", "maximum availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 100% availability. "
                    "This means ZERO downtime. Use: WHERE downtime_mins = 0 "
                )
            elif any(pattern in q_lower for pattern in ["0%", "zero percent", "no availability", "lowest availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 0% availability. "
                    "This means MAXIMUM downtime. Use: ORDER BY downtime_mins DESC "
                )
            elif "highest availability" in q_lower or "best availability" in q_lower or "most available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for highest availability. "
                    "This means LOWEST downtime. Use: ORDER BY downtime_mins ASC LIMIT 1 "
                )
            elif "lowest availability" in q_lower or "worst availability" in q_lower or "least available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for lowest availability. "
                    "This means HIGHEST downtime. Use: ORDER BY downtime_mins DESC LIMIT 1 "
                )
            else:
                hints.append(
                    "- AVAILABILITY CALCULATION: The 'availability' column does not exist. "
                    "Calculate it as: ((60.0 - downtime_mins) / 60.0) * 100 "
                    "(assuming 60-minute intervals). Use downtime_mins column from oee_details_data."
                )

        return {
            "hints": "\n".join(hints) if hints else "No specific manufacturing templates detected.",
            "corrections": corrections,
            "matched_tables": list(matched_tables)
        }


class QueryRouter:
    def __init__(self, schema: dict = None):
        self.schema = schema or {"tables": []}

    def _get_tables(self):
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
        
        is_list_tables_query = (
            ("table" in q_lower or "tables" in q_lower) and
            any(w in q_lower for w in ["list", "show", "what", "connected", "active", "available", "ist", "give", "display", "get"]) and
            not any(m in q_lower for m in ["oee", "ega", "speed", "wastage", "waste", "downtime", "failed", "bags"]) and
            not any(t in q_lower for t in ["oee_details_data", "ega_details_data", "production_speed_details_data", "wastage_records", "gsm_usage_details"])
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

        # Extract schema keywords and DB generic terms early
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
            "employee", "operator", "speed"
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

        # 4. Conceptual RAG Route
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

        # 6. Off-topic guardrail
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
                        "⚖️ Excess Giveaway Analysis (EGA)\n"
                        "⚡ Machine Production Speeds\n"
                        "🗑️ Material Wastage & Scrap Logs\n\n"
                        "Try: *'What is average OEE of machine 1?'*"
                    )
                }

        return {"type": "sql_query"}

    def _detect_ambiguity(self, q_lower: str) -> Optional[Dict]:
        filter_indicators = [
            ">", "<", "=", "above", "below", "greater", "less", "more than", 
            "higher than", "lower than", "at least", "at most", "limit", "filter"
        ]
        if any(fi in q_lower for fi in filter_indicators):
            return None

        is_short = len(q_lower.split()) <= 4
        machine_metrics = ["ega percent", "oee", "speed", "wastage"]
        machine_words = [
            "machine", "loop", "line", "m01", "m02", "m03", "l01", "l02", "l03"
        ]
        has_machine_metric = any(w in q_lower for w in machine_metrics)
        has_machine_specified = any(w in q_lower for w in machine_words)

        # Rule 1: Machine not specified
        if has_machine_metric and not has_machine_specified and is_short:
            return {
                "type": "clarification",
                "question": "Which machine or line do you want this for?",
                "suggestions": [
                    "All machines",
                    "Machine 1 (Loop 1)",
                    "Machine 2",
                    "Line 1"
                ],
                "original_query": q_lower
            }

        time_sensitive = ["ega", "oee", "efficiency", "production", "speed", "wastage"]
        time_words = [
            "today", "yesterday", "last week", "this week", "last month",
            "this month", "shift", "morning", "afternoon", "night",
            "last", "past", "recent", "from", "between", "since"
        ]
        has_time_sensitive = any(w in q_lower for w in time_sensitive)
        has_time_word = any(w in q_lower for w in time_words)

        # Rule 2: No time range
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

        # Rule 3: Vague "show me data"
        vague_triggers = ["show data", "get data", "show me data", "give data", "fetch data"]
        if any(t in q_lower for t in vague_triggers):
            return {
                "type": "clarification",
                "question": "What specific data are you looking for?",
                "suggestions": [
                    "EGA percent breakdown",
                    "OEE performance",
                    "Production speeds",
                    "Material wastage logs"
                ],
                "original_query": q_lower
            }

        # Rule 4: Comparison ambiguity
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
                        "Variant Flat Cut vs Ridge Cut"
                    ],
                    "original_query": q_lower
                }

        return None


# sql_generation.py
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import dateparser
from litellm import acompletion
from backend.config import settings
from data_layer import QueryCache, ConversationManager

logger = logging.getLogger(__name__)

# Dynamically load LLM prompts from dedicated files
PROMPTS_DIR = Path(__file__).parent / "prompts"

def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.error(f"Failed to load prompt file {path}: {e}")
        # Fallback in case of a file read emergency
        return ""

SQL_SYSTEM_PROMPT = load_prompt("sql_system.txt")
EXPLAINER_PROMPT = load_prompt("explainer.txt")

def reload_prompts():
    global SQL_SYSTEM_PROMPT, EXPLAINER_PROMPT
    SQL_SYSTEM_PROMPT = load_prompt("sql_system.txt")
    EXPLAINER_PROMPT = load_prompt("explainer.txt")
    logger.info("AI System Prompts reloaded dynamically from disk.")


# =====================================================================
# 1. NL Filter Parser (formerly nl_filter_parser.py)
# =====================================================================



# =====================================================================
# SQL Generator
# =====================================================================

class SQLGenerator:
    def __init__(self, db_connector):
        self.db = db_connector
        
        self.prompt_rag = PromptRAG()
        self.prompt_rag.index_prompts(
            rules_dir="./prompts/rules",
            examples_dir="./prompts/examples"
        )


    def sanitize_single_table_query(self, sql: str) -> str:
        # Strip notes and conversational fluff at the end of the query
        clean_lines = []
        for line in sql.splitlines():
            line_strip = line.strip()
            if not line_strip:
                continue
            if line_strip.lower().startswith(("note:", "explanation:", "here is", "corrected", "i corrected", "this sql", "sql:", "output:", "please note", "hope this", "let me know")):
                break
            clean_lines.append(line)
        sql = "\n".join(clean_lines).strip()

        sql = re.sub(r"```.*", "", sql, flags=re.DOTALL).strip()
        if ";" in sql:
            for part in sql.split(";"):
                if "select" in part.lower():
                    sql = part.strip()
                    break
        sql = sql.strip().rstrip(";")

        group_by_match = re.search(r"GROUP\s+BY\s+(.*?)(?:ORDER|LIMIT|$)", sql, flags=re.IGNORECASE)
        if group_by_match:
            gb_cols = [c.strip() for c in group_by_match.group(1).split(',')]
            select_match = re.search(r"^SELECT\s+(.*?)FROM", sql, flags=re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1)
                missing_cols = []
                for col in gb_cols:
                    clean_col = col.split()[0]
                    if not re.search(rf"\b{re.escape(clean_col)}\b", select_clause, flags=re.IGNORECASE):
                        missing_cols.append(clean_col)
                if missing_cols:
                    new_select = "SELECT " + ", ".join(missing_cols) + ", "
                    sql = re.sub(r"^SELECT\s+", new_select, sql, flags=re.IGNORECASE)

        if "wastage_records" in sql.lower():
            sql = re.sub(r"\bstart_time\b", "production_start_time", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*1['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*2['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"]Shift\s*3['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*1%['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*2%['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*ILIKE\s*['\"]%Shift\s*3%['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Morning Shift|Morning)['\"]", "shift = 'A'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Afternoon Shift|Afternoon)['\"]", "shift = 'B'", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bshift\s*=\s*['\"](?:Night Shift|Night)['\"]", "shift = 'C'", sql, flags=re.IGNORECASE)

        sql_upper = sql.upper()
        join_keywords = ["JOIN", "INNER", "LEFT", "RIGHT", "CROSS", "OUTER"]
        if any(re.search(rf"\b{kw}\b", sql_upper) for kw in join_keywords):
            return sql
            
        if "," in sql:
            from_idx = sql_upper.find("FROM")
            if from_idx != -1:
                where_idx = sql_upper.find("WHERE", from_idx)
                sub_from_to_where = sql[from_idx:where_idx] if where_idx != -1 else sql[from_idx:]
                if "," in sub_from_to_where:
                    return sql

        from_pattern = r"\bFROM\s+([a-zA-Z0-9_.]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?"
        from_match = re.search(from_pattern, sql, flags=re.IGNORECASE)
        if not from_match:
            return sql
            
        table_name = from_match.group(1)
        alias = from_match.group(2)
        if alias and alias.upper() in ["WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "ON", "JOIN", "INNER", "LEFT", "RIGHT"]:
            alias = None
        if alias:
            pattern = rf"\bFROM\s+{table_name}\s+(?:AS\s+)?{alias}\b"
            sql = re.sub(pattern, f"FROM {table_name}", sql, flags=re.IGNORECASE)
            sql = re.sub(rf"\b{alias}\.", "", sql, flags=re.IGNORECASE)
        sql = re.sub(rf"\b{table_name}\.", "", sql, flags=re.IGNORECASE)
        return sql

    def _format_schema(self, schema_info: dict) -> str:
        lines = []
        for table in schema_info.get("tables", []):
            row_count = table.get("row_count", 0)
            status = f"({row_count:,} rows)" if row_count > 0 else "(0 rows - EMPTY)"
            lines.append(f"Table: {table['name']} {status}")
            cols = [f"{c['name']} ({c['type']})" for c in table.get("columns", [])]
            lines.append("  Columns: " + ", ".join(cols))
            if table.get("samples"):
                lines.append(f"  Sample row: {table['samples'][0]}")
        return "\n".join(lines)
    
    async def extract_intent(self, query: str) -> dict:
        import json
        from litellm import acompletion
        
        prompt = """Extract the user's intent as a JSON object.
Valid metrics: 'gsm_consumption', 'oee_percent', 'ega_percent', 'quality_percent', 'availability_percent', 'production_kg', 'mttr', 'mtbf', 'wastage_kg', 'unknown'.
Return ONLY a raw JSON object.
Example 1: {"metric": "gsm_consumption", "filters": {"vendor": "ABC"}}
Example 2: {"metric": "oee_percent", "filters": {"machine_id": 4, "date": "2025-05-28"}}
Example 3: {"metric": "unknown", "filters": {}}
For time queries use 'date' (YYYY-MM-DD) or 'time_range' (e.g. 'last_7_days', 'this_week')."""
        
        try:
            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": query}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.0
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            return json.loads(content.strip())
        except Exception as e:
            logger.error(f"Intent extraction failed: {e}")
            return {"metric": "unknown", "filters": {}}

    def build_sql_from_template(self, intent: dict, time_filter: str = None) -> str:
        import json
        try:
            with open("./prompts/formulas.json", "r") as f:
                catalog = json.load(f)
        except Exception:
            return None
            
        metric = intent.get("metric")
        if metric not in catalog:
            return None
            
        sql_template = catalog[metric]
        filters = intent.get("filters", {})
        where_clauses = []
        
        if "machine_id" in filters and filters["machine_id"]:
            where_clauses.append(f"machine_id = {filters['machine_id']}")
            
        if time_filter:
            time_col = "production_start_time" if "wastage" in metric else "start_time"
            if metric == "gsm_consumption":
                time_col = "date"
            import re
            cleaned_filter = re.sub(r'\b(timestamp|unix_timestamp|start_time|production_start_time|date)\b', time_col, time_filter)
            where_clauses.append(cleaned_filter)
        else:
            if "date" in filters and filters["date"]:
                raw_date = str(filters["date"]).strip()
                time_col = "production_start_time" if "wastage" in metric else "start_time"
                if metric == "gsm_consumption":
                    time_col = "date"
                # Only use if it's a full valid YYYY-MM-DD (not partial like "2025-05")
                import re as _re
                if _re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date):
                    where_clauses.append(f"{time_col}::date = '{raw_date}'")
                else:
                    logger.warning(f"Skipping invalid LLM-extracted date '{raw_date}' — not YYYY-MM-DD format")
            if "time_range" in filters and filters["time_range"]:
                time_col = "production_start_time" if "wastage" in metric else "start_time"
                if metric == "gsm_consumption":
                    time_col = "date"
                if "7_days" in filters["time_range"]:
                    where_clauses.append(f"{time_col} >= CURRENT_DATE - INTERVAL '7 days'")
                elif "last_month" in filters["time_range"] or filters["time_range"] == "last_month":
                    where_clauses.append(
                        f"{time_col} >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') "
                        f"AND {time_col} < date_trunc('month', CURRENT_DATE)"
                    )
                elif "this_month" in filters["time_range"] or filters["time_range"] == "this_month":
                    where_clauses.append(f"{time_col} >= date_trunc('month', CURRENT_DATE)")
                elif "week" in filters["time_range"]:
                    where_clauses.append(f"{time_col} >= date_trunc('week', CURRENT_DATE)")
                
        where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        return sql_template.format(where_clause=where_str)
        
    async def generate_sql(self, query: str, schema_info: dict, domain_hints: str, max_retries: int = 1, matched_tables: list = None, time_filter: str = None) -> Tuple[str, list]:
        # Retrieve dynamically matching rules from PromptRAG (vector similarity)
        rules_meta_list = []
        try:
            rules_str, examples_str, rules_meta_list = self.prompt_rag.get_relevant_prompt_context(query, top_rules=None, top_examples=2)
            if rules_str:
                domain_hints = f"{domain_hints}\n\n═══════════════════════════════════════════════════\nSEMANTICALLY RELEVANT RULES:\n═══════════════════════════════════════════════════\n{rules_str}"
            if examples_str:
                domain_hints = f"{domain_hints}\n\n═══════════════════════════════════════════════════\nSEMANTICALLY RELEVANT EXAMPLES:\n═══════════════════════════════════════════════════\n{examples_str}"
        except Exception as e:
            logger.error(f"Failed to query PromptRAG: {e}")

        if matched_tables:
            domain_hints = f"{domain_hints}\n\nCONFIRMED RELEVANT TABLES TO USE: {', '.join(matched_tables)}"
        schema_text = self._format_schema(schema_info)
        prompt = SQL_SYSTEM_PROMPT.format(schema_text=schema_text, domain_hints=domain_hints)
        
        print("\n" + "=" * 60)
        print("💡 [FORMULA & DOMAIN HINTS REACHING LLM] 💡")
        print(domain_hints)
        print("-" * 60)
        print("🔥 [FULL SQL GENERATOR SYSTEM PROMPT] 🔥")
        print(prompt)
        print("=" * 60 + "\n")
        
        logger.info(f"Domain hints reaching LLM:\n{domain_hints}")
        logger.info(f"Generating SQL for query: '{query}'")
        
        # --- HYBRID A+C: Step 1 - Extract Intent ---
        intent = await self.extract_intent(query)
        logger.info(f"Extracted Intent: {intent}")
        
        # --- HYBRID A+C: Step 2 - Lookup Catalog ---
        if intent.get("metric") and intent.get("metric") != "unknown":
            sql = self.build_sql_from_template(intent, time_filter=time_filter)
            if sql:
                logger.info(f"Routing to pre-verified template for {intent['metric']}")
                return sql, rules_meta_list
                
        # --- HYBRID A+C: Step 3 - Fallback to Generator (with Reflection Loop) ---
        logger.info(f"Full System Prompt sent to LLM:\n{prompt}")
        
        last_error = None
        last_sql = None
        
        for attempt in range(max_retries + 1):
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": query}
            ]
            
            if last_error and last_sql:
                import re as _re
                err_lower = last_error.lower()
                if "undefinedcolumn" in err_lower or ("column" in err_lower and "does not exist" in err_lower):
                    col_match = _re.search(r'column ["\']?(\S+?)["\']? does not exist', last_error, _re.IGNORECASE)
                    bad_col = col_match.group(1) if col_match else "unknown"
                    correction_hint = (
                        f"ERROR TYPE: UndefinedColumn — column '{bad_col}' does not exist.\n"
                        f"FIX: Check the DATABASE SCHEMA. Common mistakes:\n"
                        f"- oee_details_data has NO plant_id or line_id column.\n"
                        f"- No 'oee' column exists — use downtime_mins, good_bags, failed_bags.\n"
                        f"- Time column for OEE/EGA is 'start_time', for wastage is 'production_start_time'.\n"
                        f"- Do NOT join oee_details_data to gmiiot_plants (impossible join)."
                    )
                elif "undefinedfunction" in err_lower or "operator does not exist" in err_lower:
                    correction_hint = (
                        f"ERROR TYPE: TypeMismatch — you joined or compared columns of incompatible types.\n"
                        f"FIX: plant_id on gmiiot_plants is INTEGER. "
                        f"Use ILIKE for text matching. Check JOIN column types match."
                    )
                elif "syntax" in err_lower:
                    correction_hint = (
                        f"ERROR TYPE: SyntaxError.\n"
                        f"FIX: Check for missing FROM clause, unmatched parentheses, "
                        f"missing quotes around string values, or invalid GROUP BY."
                    )
                elif "undefinedtable" in err_lower or ("relation" in err_lower and "does not exist" in err_lower):
                    tbl_match = _re.search(r'relation ["\']?(\S+?)["\']? does not exist', last_error, _re.IGNORECASE)
                    bad_tbl = tbl_match.group(1) if tbl_match else "unknown"
                    correction_hint = (
                        f"ERROR TYPE: UndefinedTable — table '{bad_tbl}' does not exist.\n"
                        f"FIX: Only use tables listed in the DATABASE SCHEMA above."
                    )
                else:
                    correction_hint = f"ERROR: {last_error[:300]}"

                messages.append({"role": "assistant", "content": last_sql})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous SQL failed. Diagnosis:\n\n{correction_hint}\n\n"
                        f"BROKEN SQL:\n{last_sql}\n\n"
                        f"Write the corrected SQL. Return ONLY the SQL starting with SELECT."
                    )
                })
                logger.info(f"Retry {attempt} — self-healing with classified error: {correction_hint[:80]}")
            
            try:
                log_msg = f"\n🚀 [SENDING TO LLM: SQL GENERATION - ATTEMPT {attempt + 1}] 🚀\n{json.dumps(messages, indent=2)}\n" + "=" * 60 + "\n"
                print(log_msg)

                response = await acompletion(
                    model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                    messages=messages,
                    api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                    temperature=0.0,
                    timeout=300
                )
                sql = response.choices[0].message.content.strip()

                log_msg = f"\n✅ [RECEIVED FROM LLM: SQL GENERATION - ATTEMPT {attempt + 1}] ✅\n{sql}\n" + "=" * 60 + "\n"
                print(log_msg)
                
                sql_blocks = re.findall(r"```sql\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                if not sql_blocks:
                    sql_blocks = re.findall(r"```\s*(.*?)\s*```", sql, flags=re.DOTALL | re.IGNORECASE)
                
                if sql_blocks:
                    sql = sql_blocks[-1].strip()
                else:
                    last_start = -1
                    marker_len = 0
                    for marker in ["```sql", "```SQL", "```"]:
                        idx = sql.rfind(marker)
                        if idx > last_start:
                            last_start = idx
                            marker_len = len(marker)
                    
                    if last_start != -1:
                        sql = sql[last_start + marker_len:].strip()
                        sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                    else:
                        select_match = re.search(r"\bSELECT\b", sql, flags=re.IGNORECASE)
                        if select_match:
                            sql = sql[select_match.start():].strip()
                        else:
                            sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"^```\s*", "", sql, flags=re.IGNORECASE)
                            sql = re.sub(r"\s*```$", "", sql, flags=re.IGNORECASE)
                
                sql = sql.strip().rstrip(";")
                sql = self.sanitize_single_table_query(sql)
                
                try:
                    await self.db.execute_query(f"EXPLAIN {sql}")
                    logger.info(f"Generated and validated SQL: {sql}")
                    return sql, rules_meta_list
                except Exception as validation_error:
                    last_error = str(validation_error)
                    last_sql = sql
                    error_msg = str(validation_error)
                    if "column" in error_msg.lower() and "does not exist" in error_msg.lower():
                        error_msg += "\n\nTROUBLESHOOTING: Check if column name exists in schema. Common mistakes:\n"
                        error_msg += "- Using 'machine_name' instead of 'machine_id'\n"
                        error_msg += "- Missing 'g' suffix in grammage values (e.g., grammage = '10.5g' not grammage = 10.5)"
                    elif "syntax" in error_msg.lower():
                        error_msg += "\n\nTROUBLESHOOTING: Check SQL syntax. Common issues:\n"
                        error_msg += "- Missing quotes around string values (e.g., variant = 'Ridge Cut')\n"
                        error_msg += "- Incorrect WHERE clause structure"
                    
                    logger.warning(f"SQL validation failed (attempt {attempt + 1}): {error_msg}")
                    last_error = error_msg
                    if attempt == max_retries:
                        raise Exception(error_msg)
                    
            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"SQL Generation failed after {max_retries + 1} attempts: {e}")
                    raise e
                last_error = str(e)
        
        raise Exception(f"SQL generation failed after {max_retries + 1} attempts")

    async def explain_results(self, query: str, sql: str, results: dict, extra_context: str = "") -> str:
        try:
            sample_results = json.dumps(results.get("rows", [])[:20], indent=2)
        except Exception as e:
            logger.error(f"Error serializing results: {e}")
            sample_results = str(results.get("rows", []))
        
        row_count = results.get("row_count", 0)
        is_count_query = False
        if row_count == 1 and results.get("rows"):
            try:
                row_data = results["rows"][0]
                if isinstance(row_data, dict) and len(row_data) == 1:
                    key = list(row_data.keys())[0]
                    if key.lower() in ["count", "total", "count(*)"]:
                        is_count_query = True
            except Exception:
                pass
        
        empty_result_guidance = ""
        if row_count == 0 or (is_count_query and results.get("rows") and len(results["rows"]) > 0):
            try:
                if is_count_query:
                    count_value = list(results["rows"][0].values())[0]
                    if count_value == 0:
                        empty_result_guidance = """\n\nIMPORTANT: The result is empty or zero. You MUST:
1. Clearly state what was found (or not found)
2. Provide 2-3 possible reasons why this might be the case (e.g., date not in database, no matching variant, machine not recorded)
3. Suggest checking available dates or alternative filters
4. Ask helpful follow-up questions to guide the user

Example format:
"Based on the query results, there are 0 [items] matching your criteria. This could mean:
- The date you specified may not have data in the database
- The variant or machine ID might not match exactly
- Data for that period hasn't been recorded yet

To investigate further, you might want to:
- Check what dates are available in the database
- Verify the exact variant names or machine IDs
- Try a broader date range

Would you like me to show you available dates or machines?"
"""
                else:
                    empty_result_guidance = """\n\nIMPORTANT: No rows were returned. You MUST:
1. Clearly state that no matching records were found
2. Suggest 2-3 possible reasons (date mismatch, variant name mismatch, no data for that period)
3. Offer to check available dates, variants, or machines
4. Be helpful and proactive in guiding the user"""
            except Exception:
                pass
        
        prompt = EXPLAINER_PROMPT.format(
            query=query,
            sql=sql,
            columns=results.get("columns", []),
            row_count=row_count,
            sample_results=sample_results
        ) + empty_result_guidance
        
        if extra_context:
            prompt = f"ADDITIONAL CONTEXT FROM RAG DOCUMENTS:\n{extra_context}\n\n---\n\n{prompt}"
        
        logger.info(f"Explaining results for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: EXPLAIN RESULTS] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            explanation = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: EXPLAIN RESULTS] ✅\n{explanation}\n" + "=" * 60 + "\n"
            print(log_msg)

            return explanation
        except Exception as e:
            logger.error(f"Explanation generation failed: {e}")
            raise e

    async def explain_rag_concept(self, query: str, rag_context: str) -> str:
        """
        Explain a conceptual manufacturing question directly using RAG reference documents.
        """
        fallback_rag_prompt_template = load_prompt("fallback_rag.txt")
        prompt = fallback_rag_prompt_template.format(
            query=query, 
            rag_context=rag_context if rag_context else 'No reference material found.'
        )
        logger.info(f"Explaining RAG concept for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: RAG CONCEPT EXPLANATION] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            response_content = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: RAG CONCEPT EXPLANATION] ✅\n{response_content}\n" + "=" * 60 + "\n"
            print(log_msg)

            return response_content
        except Exception as e:
            logger.error(f"RAG Explanation generation failed: {e}")
            raise e

    async def explain_error_conversational(self, query: str, error_msg: str, stage: str) -> str:
        """
        Explain a SQL generator or database execution error to the user in a friendly,
        plain-English way, and ask a clarifying question so the user can understand and help us fix it.
        """
        fallback_error_prompt_template = load_prompt("fallback_error.txt")
        prompt = fallback_error_prompt_template.format(
            query=query,
            stage=stage,
            error_msg=error_msg
        )
        logger.info(f"Explaining database error conversationally for query: '{query}'")
        try:
            log_msg = "\n" + "=" * 60 + f"\n🚀 [SENDING TO LLM: ERROR CONVERSATIONAL EXPLANATION] 🚀\n{prompt}\n" + "=" * 60 + "\n"
            print(log_msg)

            response = await acompletion(
                model=f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
                messages=[{"role": "user", "content": prompt}],
                api_base=settings.OLLAMA_BASE_URL if settings.LLM_PROVIDER == "ollama" else None,
                temperature=0.3,
                timeout=300
            )
            response_content = response.choices[0].message.content.strip()

            log_msg = f"\n✅ [RECEIVED FROM LLM: ERROR CONVERSATIONAL EXPLANATION] ✅\n{response_content}\n" + "=" * 60 + "\n"
            print(log_msg)

            return response_content
        except Exception as e:
            logger.error(f"Error explanation generation failed: {e}")
            raise e

"""
Validation & Sanitation Layer - Validates queries, execution metrics, and maps entity types
"""
import re
from typing import Dict, List, Tuple, Any
from decimal import Decimal

class SQLValidator:
    """Validates generated SQL against known error patterns"""
    
    # Tables that MUST use GROUP BY when date-filtered
    TIME_SERIES_TABLES = {
        "oee_details_data", 
        "ega_details_data", 
        "production_speed_details_data",
        "wastage_records"
    }
    
    # Columns that don't exist but LLMs hallucinate
    NONEXISTENT_COLUMNS = {
        "oee_details_data": ["oee", "availability", "performance", "quality", "quality_percentage"],
        "ega_details_data": [],  # machine_name exists, removing from blacklist
        "machines": ["loop_name", "loop_id"]
    }
    
    def validate(self, sql: str, user_query: str = "") -> Tuple[bool, List[str], str]:
        """
        Returns: (is_valid, warnings, corrected_sql)
        """
        sql_lower = sql.lower()
        warnings = []
        corrected_sql = sql
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 1: Date filter without GROUP BY (MOST COMMON)
        # ═══════════════════════════════════════════════════════════════
        has_date_filter = bool(re.search(r"(start_time|production_start_time)::date\s*=", sql_lower))
        has_group_by = "group by" in sql_lower
        
        if has_date_filter and not has_group_by:
            # Check if it's a time-series table
            for table in self.TIME_SERIES_TABLES:
                if table in sql_lower:
                    warnings.append(
                        f"🚨 CRITICAL: Date filter on {table} WITHOUT GROUP BY. "
                        f"This returns only 1 hourly row instead of daily aggregate!"
                    )
                    
                    # Auto-fix: Add GROUP BY machine_id
                    if "machine_id" in sql_lower and ("group by" not in sql_lower or "machine_id" not in re.search(r"group by.*", sql_lower, re.IGNORECASE | re.DOTALL).group(0)):
                        # Extract existing ORDER BY and LIMIT
                        order_match = re.search(r"(ORDER BY.*?)(?:LIMIT|\Z)", sql, re.IGNORECASE | re.DOTALL)
                        order_clause = order_match.group(1).strip() if order_match else ""
                        
                        limit_match = re.search(r"(LIMIT \d+)", sql, re.IGNORECASE)
                        limit_clause = limit_match.group(1) if limit_match else ""
                        
                        # Remove existing ORDER BY and LIMIT
                        base_sql = re.sub(r"ORDER BY.*", "", sql, flags=re.IGNORECASE | re.DOTALL).strip()
                        
                        # Resolve column names and prefixes to avoid PostgreSQL AmbiguousColumnError
                        group_cols = []
                        if "join" in sql_lower:
                            # Resolve time-series table alias
                            tbl_alias = None
                            for ts_table in self.TIME_SERIES_TABLES:
                                if ts_table in sql_lower:
                                    alias_match = re.search(rf"\b{ts_table}\s+(\w+)\b", sql, re.IGNORECASE)
                                    if alias_match and alias_match.group(1).lower() not in ("join", "inner", "left", "right", "where", "group", "order", "on"):
                                        tbl_alias = alias_match.group(1)
                                    else:
                                        tbl_alias = ts_table
                                    break
                            
                            # Resolve machines table alias
                            m_alias = None
                            if "machines" in sql_lower:
                                m_alias_match = re.search(r"\bmachines\s+(\w+)\b", sql, re.IGNORECASE)
                                if m_alias_match and m_alias_match.group(1).lower() not in ("join", "inner", "left", "right", "where", "group", "order", "on"):
                                    m_alias = m_alias_match.group(1)
                                else:
                                    m_alias = "machines"

                            if tbl_alias:
                                group_cols.append(f"{tbl_alias}.machine_id")
                            else:
                                group_cols.append("machine_id")

                            if "machine_name" in sql_lower:
                                if m_alias:
                                    group_cols.append(f"{m_alias}.machine_name")
                                elif tbl_alias:
                                    group_cols.append(f"{tbl_alias}.machine_name")
                                else:
                                    group_cols.append("machine_name")
                        else:
                            group_cols.append("machine_id")
                            if "machine_name" in sql_lower:
                                group_cols.append("machine_name")

                        group_by_cols = ", ".join(group_cols)
                        corrected_sql = f"{base_sql} GROUP BY {group_by_cols} {order_clause} {limit_clause}".strip()
                        warnings.append(f"✅ AUTO-FIX: Added 'GROUP BY {group_by_cols}'")
         
        # ═══════════════════════════════════════════════════════════════
        # ERROR 2: Impossible quality percentage (>100%)
        # ═══════════════════════════════════════════════════════════════
        if "quality" in sql_lower and "good_bags" in sql_lower:
            # Check for missing data validation
            if "good_bags >= 0" not in sql_lower and "good_bags > 0" not in sql_lower:
                warnings.append(
                    "⚠️  WARNING: Quality calculation without data validation. "
                    "Corrupt/negative values will cause impossible percentages!"
                )
                
                # Auto-fix: Add WHERE clause for data validation
                if "WHERE" in sql:
                    corrected_sql = re.sub(
                        r"WHERE\s+",
                        "WHERE good_bags >= 0 AND failed_bags >= 0 AND ",
                        corrected_sql,
                        count=1,
                        flags=re.IGNORECASE
                    )
                else:
                    # Add WHERE before GROUP BY
                    corrected_sql = re.sub(
                        r"\s+(GROUP BY|ORDER BY)",
                        r" WHERE good_bags >= 0 AND failed_bags >= 0 \1",
                        corrected_sql,
                        count=1,
                        flags=re.IGNORECASE
                    )
                warnings.append("✅ AUTO-FIX: Added 'WHERE good_bags >= 0 AND failed_bags >= 0'")
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 3: Using nonexistent columns
        # ═══════════════════════════════════════════════════════════════
        for table, bad_cols in self.NONEXISTENT_COLUMNS.items():
            if table in sql_lower:
                for col in bad_cols:
                    # Match column references like "table.column" or just "column"
                    pattern = rf"\b{col}\b"
                    if re.search(pattern, sql_lower):
                        warnings.append(
                            f"🚨 CRITICAL: Column '{col}' does NOT exist in {table}!"
                        )
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 4: Wrong ORDER BY direction
        # ═══════════════════════════════════════════════════════════════
        if "worst" in user_query.lower() or "lowest" in user_query.lower() or "fewest" in user_query.lower():
            if re.search(r"ORDER BY.*DESC", corrected_sql, re.IGNORECASE):
                warnings.append(
                    "🚨 CRITICAL: Query asks for 'worst/lowest' but uses ORDER BY DESC. "
                    "Should be ASC for worst/lowest!"
                )
                corrected_sql = re.sub(r"DESC", "ASC", corrected_sql, flags=re.IGNORECASE)
                warnings.append("✅ AUTO-FIX: Changed ORDER BY DESC to ASC")
        
        if "best" in user_query.lower() or "highest" in user_query.lower() or "most" in user_query.lower():
            if re.search(r"ORDER BY.*ASC", corrected_sql, re.IGNORECASE):
                warnings.append(
                    "🚨 CRITICAL: Query asks for 'best/highest' but uses ORDER BY ASC. "
                    "Should be DESC for best/highest!"
                )
                corrected_sql = re.sub(r"ASC", "DESC", corrected_sql, flags=re.IGNORECASE)
                warnings.append("✅ AUTO-FIX: Changed ORDER BY ASC to DESC")
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 5: COUNT instead of SUM for aggregates
        # ═══════════════════════════════════════════════════════════════
        if re.search(r"COUNT\((good_bags|failed_bags|downtime_mins|wastage_kg)\)", sql, re.IGNORECASE):
            warnings.append(
                "🚨 CRITICAL: Using COUNT() on metric columns! Should use SUM() for totals."
            )
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 6: Grammage with 'g' suffix
        # ═══════════════════════════════════════════════════════════════
        if re.search(r"grammage\s*=\s*['\"][\d.]+g", sql_lower):
            warnings.append(
                "⚠️  WARNING: Grammage compared with 'g' suffix. Should be numeric (e.g., 10.5 not '10.5g')"
            )
            # Auto-fix: Remove 'g' suffix from grammage comparisons
            corrected_sql = re.sub(
                r"(grammage\s*=\s*['\"])([\d.]+)g(['\"])",
                r"\1\2\3",
                corrected_sql,
                flags=re.IGNORECASE
            )
            # Better: convert to numeric comparison
            corrected_sql = re.sub(
                r"grammage\s*=\s*['\"]?([\d.]+)g?['\"]?",
                r"grammage = \1",
                corrected_sql,
                flags=re.IGNORECASE
            )
            warnings.append("✅ AUTO-FIX: Converted grammage to numeric comparison")
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 7: Missing machine_id/machine_name in SELECT when GROUP BY
        # ═══════════════════════════════════════════════════════════════
        if has_group_by and "machine_id" in sql_lower:
            group_by_match = re.search(r"GROUP BY\s+([^;]+?)(?:ORDER BY|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
            if group_by_match:
                group_cols = group_by_match.group(1).lower()
                if "machine_id" in group_cols:
                    # Check if machine_id is in SELECT
                    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
                    if select_match:
                        select_cols = select_match.group(1).lower()
                        if "machine_id" not in select_cols and "*" not in select_cols:
                            warnings.append(
                                "⚠️  WARNING: GROUP BY machine_id but machine_id not in SELECT. "
                                "Results won't show which machine!"
                            )
        
        # ═══════════════════════════════════════════════════════════════
        # ERROR 8: Division without NULLIF
        # ═══════════════════════════════════════════════════════════════
        if re.search(r"/\s*\(?\s*SUM\(", sql, re.IGNORECASE):
            if "NULLIF" not in sql:
                warnings.append(
                    "⚠️  WARNING: Division by SUM() without NULLIF. Risk of division-by-zero error!"
                )
        
        # Determine if SQL is valid (no CRITICAL errors)
        is_valid = not any("🚨 CRITICAL" in w for w in warnings)
        
        return is_valid, warnings, corrected_sql


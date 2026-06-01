import logging
from typing import List, Dict
import chromadb
from chromadb import EmbeddingFunction
from chromadb.config import Settings as ChromaSettings
from backend.config import settings
import requests

logger = logging.getLogger(__name__)

class OllamaEmbeddingFunction(EmbeddingFunction):
    """Callable that sends texts to an Ollama server and returns embeddings.
    Inherits from chromadb.EmbeddingFunction to avoid validation issues.
    """
    def __init__(self, model_name: str, url: str):
        self.model_name = model_name
        self.url = url

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Chroma passes the parameter as 'input', but we can map it
        inputs = input
        embeddings: List[List[float]] = []
        for text in inputs:
            try:
                # Truncate text to 1000 characters to fit safely within the 512-token context limit
                safe_text = text[:1000]
                response = requests.post(
                    self.url,
                    json={"model": self.model_name, "prompt": safe_text},
                    timeout=180,
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
            except Exception as e:
                logger.error(f"Failed to embed text (len={len(text)}): {e}")
                # Return a zero‑vector of the expected dimension (384 for all‑minilm)
                embeddings.append([0.0] * 384)
        return embeddings

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
        """Index all tables from a ``schema`` dict, creating embeddings for the
        full table as well as individual columns to support high-precision retrieval.
        """
        tables = schema.get("tables", [])
        if not tables:
            logger.warning("No tables found to embed.")
            return

        ids, documents, metadatas = [], [], []

        for tbl in tables:
            table_name = tbl.get("name", "")
            if not table_name:
                continue

            # 1. Embed the table as a whole
            ids.append(f"{table_name}::table")
            documents.append(self._table_to_text(tbl))
            metadatas.append({"table_name": table_name, "type": "table"})

            # 2. Embed each column individually (column-level embeddings)
            for col in tbl.get("columns", []):
                col_name = col.get("name", "")
                if not col_name:
                    continue

                col_desc = col.get("description", "")
                col_synonyms = col.get("synonyms", [])

                desc_str = f"Table: {table_name}. Column: {col_name}"
                if col_desc:
                    desc_str += f". Description: {col_desc}"
                if col_synonyms:
                    desc_str += f". Synonyms: {', '.join(col_synonyms)}"

                ids.append(f"{table_name}::column::{col_name}")
                documents.append(desc_str)
                metadatas.append({"table_name": table_name, "type": "column", "column_name": col_name})

        logger.info("Embedding %d items (tables + columns) into ChromaDB…", len(ids))
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Schema embedding complete.")

    def query(self, user_question: str, top_k: int = 3) -> List[str]:
        """Return the *names* of the most relevant tables for ``user_question``.
        Uses the same embedding function for the query text.
        """
        q_emb = self.ef([user_question])
        # Capping n_results to collection size
        collection_size = self.collection.count()
        n_results = min(top_k * 3, collection_size)

        if n_results == 0:
            return []

        results = self.collection.query(query_embeddings=q_emb, n_results=n_results) # Request more to account for column duplicates

        if not results.get("metadatas") or not results["metadatas"][0]:
            return []

        # Deduplicate table names while preserving rank order
        seen = set()
        table_names = []
        for metadata in results["metadatas"][0]:
            t_name = metadata.get("table_name")
            if t_name and t_name not in seen:
                seen.add(t_name)
                table_names.append(t_name)
                if len(table_names) >= top_k:
                    break

        return table_names
    
    def query_with_scores(self, user_question: str, top_k: int = 5, distance_threshold: float = 1.2) -> List[tuple]:
        """Return table names with their best distance scores, filtered by threshold.
        ChromaDB returns L2 distance — lower is better.
        """
        q_emb = self.ef([user_question])
        # Fetch more candidates because many could belong to the same table (e.g. multiple columns matched)
        collection_size = self.collection.count()
        n_results = min(top_k * 5, collection_size)

        if n_results == 0:
            return []

        results = self.collection.query(
            query_embeddings=q_emb, 
            n_results=n_results,
            include=["distances", "metadatas"]
        )
        
        if not results.get("distances") or not results.get("metadatas") or not results["distances"][0]:
            return []
        
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]

        # Aggregate the best (lowest) score for each table
        table_best_scores = {}
        for dist, meta in zip(distances, metadatas):
            t_name = meta.get("table_name")
            if not t_name:
                continue

            if t_name not in table_best_scores or dist < table_best_scores[t_name]:
                table_best_scores[t_name] = dist

        # Filter by distance threshold and sort
        filtered = [
            (t_name, dist) for t_name, dist in table_best_scores.items()
            if dist < distance_threshold
        ]

        # Sort by distance (ascending)
        filtered.sort(key=lambda x: x[1])

        # Return top_k
        filtered = filtered[:top_k]
        
        logger.info(f"Query returned {len(filtered)} tables after score filtering (threshold={distance_threshold})")
        
        return filtered

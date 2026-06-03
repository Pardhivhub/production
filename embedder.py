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

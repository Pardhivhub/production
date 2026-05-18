# table_selector.py
import logging
from typing import List, Dict
from embedder import SchemaEmbedder

logger = logging.getLogger(__name__)

class TableSelector:
    """
    Retrieves the most relevant tables for a user question by:
    1. Embedding the complete schema once (handled by SchemaEmbedder).
    2. Querying the same collection with the question vector.
    3. Filtering by confidence scores to avoid irrelevant tables.
    """
    def __init__(self, schema: Dict):
        self.schema = schema
        self.embedder = SchemaEmbedder()
        # Index the schema the first time the selector is created
        self.embedder.embed_schema(schema)

    def select_relevant_tables(self, user_question: str, top_k: int = 5, distance_threshold: float = 1.2) -> Dict:
        """
        Returns a dictionary with a single key ``tables`` that contains the
        full table objects (name, columns, description, samples) for the
        top‑k matches, filtered by distance threshold.
        """
        # Try with score filtering first
        scored = self.embedder.query_with_scores(user_question, top_k=top_k, distance_threshold=distance_threshold)
        
        # Fallback: if no tables pass threshold, take top 2 anyway
        if not scored:
            logger.warning(f"No tables passed distance threshold {distance_threshold}, falling back to top 2")
            table_names = self.embedder.query(user_question, top_k=2)
        else:
            table_names = [name for name, _ in scored]
        
        selected = [t for t in self.schema.get("tables", []) if t["name"] in table_names]
        logger.info("Vector‑based selection → %s (scores: %s)", ", ".join(table_names), scored if scored else "fallback")
        return {"tables": selected}

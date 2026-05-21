# table_selector.py
import logging
from typing import List, Dict
from embedder import SchemaEmbedder
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

class TableSelector:
    """
    Retrieves the most relevant tables for a user question by using a hybrid 3-layer approach:
    1. Keyword Exact Match: Immediate matching of domain terms.
    2. BM25 Sparse Retrieval: Partial/exact word matches on table and column names.
    3. Vector Search (Semantic): Fallback/complement using ChromaDB embeddings.
    4. Union and Ranking: Combines and deduplicates results.
    """
    def __init__(self, schema: Dict):
        self.schema = schema
        self.embedder = SchemaEmbedder()
        # Index the schema the first time the selector is created
        self.embedder.embed_schema(schema)
        self._init_bm25()

    def _init_bm25(self):
        """Initializes the BM25 index with table and column names."""
        self.bm25_corpus = []
        self.bm25_table_mapping = []

        for table in self.schema.get("tables", []):
            table_name = table.get("name", "")
            if not table_name:
                continue

            # Document 1: Table name
            self.bm25_corpus.append(table_name.replace("_", " ").lower().split())
            self.bm25_table_mapping.append(table_name)

            # Document 2: All column names combined
            col_names = []
            for col in table.get("columns", []):
                c_name = col.get("name", "").replace("_", " ").lower()
                if c_name:
                    col_names.extend(c_name.split())

            if col_names:
                self.bm25_corpus.append(col_names)
                self.bm25_table_mapping.append(table_name)

        if self.bm25_corpus:
            self.bm25 = BM25Okapi(self.bm25_corpus)
        else:
            self.bm25 = None

    def select_relevant_tables(self, user_question: str, top_k: int = 5, distance_threshold: float = 1.2) -> Dict:
        """
        Returns a dictionary with a single key ``tables`` that contains the
        full table objects for the top matches.
        """
        q_lower = user_question.lower()
        q_clean = q_lower.replace("_", " ").replace("-", " ").replace("?", " ").replace(",", " ").replace(".", " ")
        words = set(q_clean.split())
        
        # Normalize and singularize query words
        normalized_words = set()
        for w in words:
            normalized_words.add(w)
            if w.endswith("s") and len(w) > 3:
                normalized_words.add(w[:-1])
            if w.endswith("es") and len(w) > 4:
                normalized_words.add(w[:-2])
                
        # Layer 1: Domain-specific Keyword Exact Match
        domain_keywords = {
            "feedback_data": ["feedback", "rf", "amplitude", "variant", "weigher", "topic", "speed", "zeros", "worked", "target_weight", "actual_weight", "feeder"],
            "golden_settings": ["golden", "setting", "limit", "threshold", "spec", "target", "parameter"],
            "feeder_metadata": ["feeder", "metadata", "manufacturer", "install", "maintenance"],
            "feeder_stats_line_1_jan": ["feeder", "stat", "cycles", "amplitude"],
            "live_weight_logs_candy_x": ["live", "weight", "log", "candy", "batch", "scale"],
            "rf_production_batch_a01": ["batch", "production", "amplitude", "weight"],
            "shift_assignments": ["shift", "assignment", "operator", "schedule", "staff"],
            "operator_certification_levels": ["cert", "operator", "skill", "training", "level"],
            "electric_meter_hourly": ["electric", "meter", "power", "energy", "kwh", "demand"],
            "sugar_silo_levels": ["sugar", "silo", "level"],
            "packaging_inventory": ["packaging", "inventory", "stock", "box", "material"],
            "factory_humidity_logs": ["humidity", "temp", "temperature", "environment"],
            "employees_list": ["employee", "worker", "operator", "staff", "jta", "incharge", "role", "name"],
            "ega_details_data": ["ega", "giveaway", "excess", "actual_weight", "target_weight", "variant", "grammage", "loop", "machine"],
            "oee_details_data": ["oee", "availability", "performance", "quality", "overall", "efficiency", "machine", "loop"],
            "wastage_records": ["wastage", "waste", "scrap", "reason", "line", "grammage", "operator", "jta", "incharge"]
        }
        
        table_scores = {}

        for table_name, keywords in domain_keywords.items():
            for kw in keywords:
                if kw in q_clean or any(kw in word for word in normalized_words):
                    table_scores[table_name] = table_scores.get(table_name, 0) + 10.0 # High weight for exact match

        # Layer 2: BM25 on Table and Column Names (Partial Match)
        if self.bm25:
            tokenized_query = q_clean.split()
            bm25_scores = self.bm25.get_scores(tokenized_query)
            for score, table_name in zip(bm25_scores, self.bm25_table_mapping):
                if score > 0:
                    table_scores[table_name] = table_scores.get(table_name, 0) + float(score) * 2.0 # Medium weight

        # Layer 3: Vector Semantic Matching (ChromaDB)
        vector_tables = []
        try:
            scored = self.embedder.query_with_scores(user_question, top_k=top_k, distance_threshold=distance_threshold)
            if not scored:
                vector_tables = self.embedder.query(user_question, top_k=2)
                for i, vt in enumerate(vector_tables):
                    table_scores[vt] = table_scores.get(vt, 0) + (top_k - i) * 1.0
            else:
                vector_tables = [name for name, _ in scored]
                for vt, dist in scored:
                    # dist is L2 distance, smaller is better. Invert it to a positive score contribution
                    sim_score = max(0, distance_threshold - dist) * 5.0
                    table_scores[vt] = table_scores.get(vt, 0) + sim_score
        except Exception as e:
            logger.error(f"Vector query failed in TableSelector: {e}")
            vector_tables = []
            
        # 4. Merge, Deduplicate and Rank by Combined Score
        ranked_tables = sorted(table_scores.items(), key=lambda x: x[1], reverse=True)
        final_table_names = [t[0] for t in ranked_tables[:top_k]]
        
        selected = [t for t in self.schema.get("tables", []) if t["name"] in final_table_names]
        
        logger.info(
            "Hybrid Selection → Ranked Matches: %s | Final Selected: %s",
            [(t, round(s, 2)) for t, s in ranked_tables[:top_k]],
            [t["name"] for t in selected]
        )
        
        return {"tables": selected}

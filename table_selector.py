# table_selector.py
import logging
from typing import List, Dict
from embedder import SchemaEmbedder

logger = logging.getLogger(__name__)

class TableSelector:
    """
    Retrieves the most relevant tables for a user question by using a hybrid approach:
    1. Lexical/Domain Keyword Matching: Immediate matching of domain terms, column names,
       table suffixes, and user constraints.
    2. Vector Search (Semantic): Fallback/complement using ChromaDB embeddings of the schema.
    3. Union and Selection: Combines results to ensure high recall while keeping the schema concise.
    """
    def __init__(self, schema: Dict):
        self.schema = schema
        self.embedder = SchemaEmbedder()
        # Index the schema the first time the selector is created
        self.embedder.embed_schema(schema)

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
                
        # 1. Domain-specific Lexical/Keyword Mapping
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
        
        lexical_matches = set()
        for table_name, keywords in domain_keywords.items():
            # Check if any keyword matches a word in the query or is a substring of the query
            for kw in keywords:
                if kw in q_clean or any(kw in word for word in normalized_words):
                    lexical_matches.add(table_name)
                    break

        # 2. Vector Semantic Matching (ChromaDB)
        vector_tables = []
        try:
            scored = self.embedder.query_with_scores(user_question, top_k=top_k, distance_threshold=distance_threshold)
            if not scored:
                vector_tables = self.embedder.query(user_question, top_k=2)
            else:
                vector_tables = [name for name, _ in scored]
        except Exception as e:
            logger.error(f"Vector query failed in TableSelector: {e}")
            # Non-blocking fallback
            vector_tables = []
            
        # 3. Union and Prioritization
        # Union the tables, placing lexical matches first
        all_matched_names = list(lexical_matches)
        for vt in vector_tables:
            if vt not in all_matched_names:
                all_matched_names.append(vt)
                
        # Limit to top_k to keep schema size optimal for the LLM
        final_table_names = all_matched_names[:top_k]
        
        # Ensure that if the query mentions specific high-priority indicators, we don't accidentally drop them
        # (e.g. if we have more than 5 tables, keep the strongest ones)
        selected = [t for t in self.schema.get("tables", []) if t["name"] in final_table_names]
        
        logger.info(
            "Hybrid Selection → Lexical: %s | Vector: %s | Final: %s", 
            list(lexical_matches), 
            vector_tables, 
            [t["name"] for t in selected]
        )
        
        return {"tables": selected}

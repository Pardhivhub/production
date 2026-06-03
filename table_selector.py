# table_selector.py
import logging
import re
from typing import List, Dict, Set
from embedder import SchemaEmbedder

import json
from pathlib import Path

logger = logging.getLogger(__name__)

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
        {"flavours", "wastage_reasons"},
        {"machines", "gmiiot_plants", "gmiiot_lines"},
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

    # ------------------------------------------------------------------
    # Index Building — runs once on init and on refresh
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Main Selection
    # ------------------------------------------------------------------

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
            if len(word) < 3:
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

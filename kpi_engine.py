import re
from difflib import get_close_matches

# Self-contained manufacturing formulas and aggregation logic
# Aligned precisely with the public schema of the user's 'iiot_feedback' database!
FORMULAS_CATALOG = {
  "EGA_percent": {
    "metric": "EGA_percent",
    "aliases": ["ega percent", "ega %", "ega_percentage", "ega", "excess give away percent", "extra give away percent", "excess give away %", "extra weight given away"],
    "type": "derived_kpi",
    "table": "feedback_data",
    "aggregates": {
      "AW": "SUM(actual_weight)",
      "TW": "SUM(target_weight)"
    },
    "formula": "((SUM(actual_weight) - SUM(target_weight)) / NULLIF(SUM(actual_weight), 0)) * 100",
    "query": "SELECT ((SUM(actual_weight) - SUM(target_weight)) / NULLIF(SUM(actual_weight), 0)) * 100 AS ega_percent FROM feedback_data",
    "groupable_by": ["variant", "topic", "created_at"],
    "filters": ["variant", "topic"],
    "rounding": 2
  },
  "Average_Speed": {
    "metric": "Average_Speed",
    "aliases": ["average speed", "actual speed", "production speed", "machine speed", "avg speed"],
    "type": "derived_kpi",
    "table": "feedback_data",
    "formula": "AVG(actual_speed)",
    "query": "SELECT AVG(actual_speed) AS avg_speed FROM feedback_data",
    "groupable_by": ["variant", "topic"],
    "rounding": 1
  },
  "Total_Weight_kg": {
    "metric": "Total_Weight_kg",
    "aliases": ["total production", "total actual weight", "total output", "weight produced", "total yield"],
    "type": "derived_kpi",
    "table": "feedback_data",
    "formula": "SUM(actual_weight) / 1000.0",
    "query": "SELECT SUM(actual_weight) / 1000.0 AS total_weight_kg FROM feedback_data",
    "groupable_by": ["variant"],
    "rounding": 2
  },
  "Sugar_Silo_Inventory": {
    "metric": "Sugar_Silo_Inventory",
    "aliases": ["sugar level", "sugar inventory", "silo level", "sugar level kg", "silo stock"],
    "type": "derived_kpi",
    "table": "sugar_silo_levels",
    "formula": "SUM(level_kg)",
    "query": "SELECT SUM(level_kg) AS total_sugar_kg FROM sugar_silo_levels",
    "groupable_by": ["silo_number"],
    "rounding": 1
  },
  "Power_Consumption_Cost": {
    "metric": "Power_Consumption_Cost",
    "aliases": ["electricity cost", "power cost", "energy cost", "utility cost", "cost of power"],
    "type": "derived_kpi",
    "table": "electric_meter_hourly",
    "formula": "SUM(cost)",
    "query": "SELECT SUM(cost) AS total_cost FROM electric_meter_hourly",
    "groupable_by": ["meter_id"],
    "rounding": 2
  },
  "Factory_Humidity_Avg": {
    "metric": "Factory_Humidity_Avg",
    "aliases": ["average humidity", "humidity percent", "humidity %", "air humidity"],
    "type": "derived_kpi",
    "table": "factory_humidity_logs",
    "formula": "AVG(humidity_pct)",
    "query": "SELECT AVG(humidity_pct) AS avg_humidity FROM factory_humidity_logs",
    "groupable_by": ["zone"],
    "rounding": 2
  }
}

RELATIONSHIPS_CATALOG = [
  {
    "from_table": "feedback_data",
    "from_column": "variant",
    "to_table": "golden_settings",
    "to_column": "variant",
    "type": "one-to-many",
    "description": "Link production feedback to golden setup settings via product variant"
  },
  {
    "from_table": "feeder_metadata",
    "from_column": "feeder_id",
    "to_table": "feedback_data",
    "to_column": "id",
    "type": "one-to-many",
    "description": "Link hardware feeder metadata to production feedback logs"
  }
]

SHIFT_PATTERNS = {
  "morning shift": ("06:00:00", "14:00:00", "Shift 1"),
  "afternoon shift": ("14:00:00", "22:00:00", "Shift 2"),
  "night shift": ("22:00:00", "06:00:00", "Shift 3 (Overnight Crossover)")
}

class KPIEngine:
    def __init__(self, schema_info: dict = None):
        self.schema_info = schema_info or {"tables": []}
        self.kpi_formulas = FORMULAS_CATALOG
        self.relationships = RELATIONSHIPS_CATALOG

    def compile_domain_hints(self, user_query: str) -> dict:
        q_lower = user_query.lower()
        hints = []
        corrections = {}
        matched_tables = set()

        # 1. Math aggregate and catalog metric detection
        for kpi_id, meta in self.kpi_formulas.items():
            aliases = meta.get("aliases", [kpi_id.replace("_", " ").lower()])
            if any(alias in q_lower for alias in aliases):
                metric = meta.get("metric")
                table = meta.get("table")
                formula = meta.get("formula")
                query_example = meta.get("query")
                
                hints.append(
                    f"- KPI METRIC DETECTED ({metric.upper()}): For calculating {metric}, "
                    f"use table '{table}' and formula: `{formula}`. "
                    f"Example query structure: `{query_example}`"
                )
                if table:
                    matched_tables.add(table.split(".")[-1])

        # 2. Shift Range Processing
        for shift_name, (start_t, end_t, label) in SHIFT_PATTERNS.items():
            # Match shift aliases like 'shift 1', 'morning shift', 'shift 3', 'night shift'
            alias_num = label.split()[0].lower() # 'shift 1'
            if shift_name in q_lower or alias_num in q_lower or label.lower() in q_lower:
                hints.append(
                    f"- SHIFT FILTER DETECTED ({label.upper()}): Filter timestamps using shift hours "
                    f"between '{start_t}' and '{end_t}'. Note: For overnight night shifts (22:00:00 to 06:00:00), "
                    f"use a crossover check: `(timestamp >= '22:00:00' OR timestamp < '06:00:00')`."
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

        # Prevent fuzzy matching on common SQL/English verbs and conversational words
        EXCLUDE_FUZZY = {
            "find", "show", "list", "get", "each", "what", "where", "when", "with", "have",
            "mean", "name", "date", "time", "hour", "year", "month", "week", "day", "rate",
            "cost", "peak", "free", "data", "line", "type", "from", "info", "than", "alert"
        }

        words = re.findall(r"\b\w+\b", q_lower)
        for word in words:
            if len(word) < 4 or word in EXCLUDE_FUZZY:
                continue
                
            # If the word is already a substring of any actual column, do not fuzzy correct it
            # (e.g., 'demand' is a substring of 'peak_demand_kw' — the LLM handles this perfectly)
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

        return {
            "hints": "\n".join(hints) if hints else "No specific manufacturing templates detected.",
            "corrections": corrections
        }

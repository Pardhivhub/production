import re
import json
from pathlib import Path
from difflib import get_close_matches

# Self-contained manufacturing formulas and aggregation logic
# Aligned precisely with the public schema of the user's 'iiot_feedback' database!
TIME_COLUMN_MAP = {
    "feedback_data": "unix_timestamp",
    "oee_details_data": "timestamp",
    "ega_details_data": "start_time",
    "wastage_records": "timestamp",
    "electric_meter_hourly": "timestamp",
    "sugar_silo_levels": "timestamp",
    "factory_humidity_logs": "timestamp",
    "live_weight_logs_candy_x": "timestamp",
    "rf_production_batch_a01": "timestamp",
}

FORMULAS_CATALOG = {
  "OEE": {
    "metric": "OEE",
    "aliases": ["oee", "oee performance", "machine performance", "speed efficiency", "overall equipment effectiveness", "average oee", "overall efficiency", "equipment efficiency"],
    "type": "stored_kpi",
    "table": "oee_details_data",
    "formula": "AVG(oee)",
    "query": "SELECT machine_id, loop_id, AVG(oee) AS avg_oee, AVG(availability) AS avg_availability, AVG(performance) AS avg_performance, AVG(quality) AS avg_quality FROM oee_details_data GROUP BY machine_id, loop_id",
    "time_column": "timestamp",
    "groupable_by": ["machine_id", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"]
  },
  "EGA_percent": {
    "metric": "EGA_percent",
    "aliases": ["ega", "ega percent", "ega %", "ega_percentage", "excess give away percent", "extra give away percent", "excess give away %", "extra weight given away", "excess give away", "giveaway", "extra weight"],
    "type": "stored_kpi",
    "table": "ega_details_data",
    "formula": "AVG(ega_percent)",
    "query": "SELECT machine_id, loop_id, AVG(ega_percent) AS avg_ega FROM ega_details_data GROUP BY machine_id, loop_id",
    "time_column": "start_time",
    "groupable_by": ["machine_id", "loop_id", "variant", "grammage"],
    "filters": ["machine_id", "loop_id", "variant"]
  },
  "Wastage": {
    "metric": "Wastage",
    "aliases": ["wastage", "waste", "scrap", "material loss"],
    "type": "stored_kpi",
    "table": "wastage_records",
    "formula": "SUM(wastage_kg)",
    "query": "SELECT machine_id, line_id, SUM(wastage_kg) AS total_wastage FROM wastage_records GROUP BY machine_id, line_id",
    "time_column": "timestamp",
    "groupable_by": ["machine_id", "line_id", "shift", "grammage"],
    "filters": ["machine_id", "line_id", "shift"]
  },
  "Power_Cost": {
    "metric": "Power_Cost",
    "aliases": ["electricity cost", "power cost", "energy cost", "utility cost", "cost of power", "kwh", "power consumption"],
    "type": "stored_kpi",
    "table": "electric_meter_hourly",
    "formula": "SUM(cost)",
    "query": "SELECT SUM(cost) AS total_cost, SUM(kwh_consumed) AS total_kwh, MAX(peak_demand_kw) AS peak_demand FROM electric_meter_hourly",
    "time_column": "timestamp",
    "groupable_by": ["meter_id"],
    "filters": ["meter_id"]
  },
  "Sugar_Level": {
    "metric": "Sugar_Level",
    "aliases": ["sugar level", "sugar inventory", "silo level", "sugar level kg", "silo stock"],
    "type": "stored_kpi",
    "table": "sugar_silo_levels",
    "formula": "AVG(level_kg)",
    "query": "SELECT silo_number, AVG(level_kg) AS avg_level, MIN(level_kg) AS min_level FROM sugar_silo_levels GROUP BY silo_number",
    "time_column": "timestamp",
    "groupable_by": ["silo_number"],
    "filters": ["silo_number"]
  },
  "Average_Speed": {
    "metric": "Average_Speed",
    "aliases": ["average speed", "actual speed", "production speed", "machine speed", "avg speed"],
    "type": "derived_kpi",
    "table": "feedback_data",
    "formula": "ROUND(AVG(actual_speed), 1)",
    "query": "SELECT ROUND(AVG(actual_speed), 1) AS avg_speed FROM feedback_data",
    "groupable_by": ["variant", "topic"],
    "rounding": 1
  },
  "Total_Weight_kg": {
    "metric": "Total_Weight_kg",
    "aliases": ["total production", "total actual weight", "total output", "weight produced", "total yield"],
    "type": "derived_kpi",
    "table": "feedback_data",
    "formula": "ROUND(SUM(actual_weight) / 1000.0, 2)",
    "query": "SELECT ROUND(SUM(actual_weight) / 1000.0, 2) AS total_weight_kg FROM feedback_data",
    "groupable_by": ["variant"],
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
  },
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
  },
  {
    "from_table": "wastage_records",
    "from_column": "shift",
    "to_table": "ega_details_data",
    "to_column": "start_time",
    "type": "shift-based",
    "description": "Shift-wise link based on start_time in production tables"
  },
  {
    "from_table": "wastage_records",
    "from_column": "operator_name",
    "to_table": "employees_list",
    "to_column": "name",
    "type": "many-to-one",
    "description": "Link operator in wastage record to employee master"
  },
  {
    "from_table": "wastage_records",
    "from_column": "jta_name",
    "to_table": "employees_list",
    "to_column": "name",
    "type": "many-to-one",
    "description": "Link JTA in wastage record to employee master"
  },
  {
    "from_table": "wastage_records",
    "from_column": "shift_incharge_name",
    "to_table": "employees_list",
    "to_column": "name",
    "type": "many-to-one",
    "description": "Link shift in-charge to employee master"
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

        # Prioritize feedback_data for generic 'rf' / 'feeder' / 'production' queries
        if any(w in q_lower for w in ["rf", "feeder", "amplitude", "worked", "zero", "production", "telemetry"]):
            # Specific check for counting unique RFs/feeders (which are columns, not rows)
            if "unique" in q_lower:
                hints.append(
                    "- UNIQUE RF/FEEDER COUNT RULE: The user is asking for the number of unique radial feeders (RFs) in the project, "
                    "which are defined by the unique 'rf1' through 'rf9' columns in the 'feedback_data' table. "
                    "To calculate this correctly, you MUST write a query targeting the 'information_schema.columns' catalog "
                    "to count the distinct columns matching 'rf%_amplitude' in 'feedback_data'.\n"
                    "Exact SQL to generate: `SELECT COUNT(DISTINCT column_name) FROM information_schema.columns WHERE table_name = 'feedback_data' AND column_name LIKE 'rf%_amplitude'`"
                )
            else:
                hints.append(
                    "- TABLE PRIORITIZATION HINT: The 'feedback_data' table (16,420 rows) is the primary production database "
                    "containing live telemetry logs. Columns 'rf1_amplitude' through 'rf9_amplitude', 'rf1_weight_avg' through 'rf9_weight_avg', "
                    "and 'rf1_worked_count' through 'rf9_worked_count' represent the 9 radial feeders (RF 1 to RF 9). "
                    "ALWAYS query 'feedback_data' for active production stats, OEE, speeds, and feeder amplitudes. "
                    "Do NOT use 'rf_production_batch_a01' (which contains only 3 test batch rows) unless the user explicitly asks for "
                    "'batch a01' or 'batch production'."
                )
            matched_tables.add("feedback_data")

        # Handle 'machine' and 'alert' mapping to feedback_data.topic directly
        if "alert" in q_lower and any(w in q_lower for w in ["machine", "weigher", "topic"]):
            hints.append(
                "- MACHINE ALERT RULE: The 'feedback_data' table contains live alert logs for various machines/weighers. "
                "In 'feedback_data', each machine/weigher is identified by the 'topic' column (e.g. 'weigher13_c2'). "
                "Do NOT join with 'wastage_records' or any other table to find machine-specific alerts. "
                "To find the machine with the highest alerts, count the alert rows grouped by 'topic' directly in 'feedback_data'.\n"
                "Correct SQL query structure: `SELECT topic AS machine_id, COUNT(*) AS alert_count FROM feedback_data WHERE alert IS NOT NULL AND alert != '' AND alert != '-' GROUP BY topic ORDER BY alert_count DESC LIMIT 1`"
            )
            matched_tables.add("feedback_data")
        # Handle queries about feeders that have EGA values
        if "feeder" in q_lower and "ega" in q_lower:
            # Optional numeric threshold, e.g., 'ega > 2.5'
            thresh_match = re.search(r"ega\s*([<>]=?)\s*([0-9]*\.?[0-9]+)", q_lower)
            if thresh_match:
                op, val = thresh_match.groups()
                hints.append(
                    f"- FEEDER EGA RULE: Join 'feedback_data' (topic) with 'ega_details_data' (machine_id) and return feeder columns where ega_percent {op} {val}. "
                    "SQL template: `SELECT fd.topic, fd.rf1_amplitude, fd.rf2_amplitude, fd.rf3_amplitude, fd.rf4_amplitude, fd.rf5_amplitude, fd.rf6_amplitude, fd.rf7_amplitude, fd.rf8_amplitude, fd.rf9_amplitude, eg.ega_percent FROM feedback_data fd JOIN ega_details_data eg ON fd.topic = eg.machine_id WHERE eg.ega_percent " + op + " " + val + "`"
                )
                matched_tables.update({"feedback_data", "ega_details_data"})
            else:
                hints.append(
                    "- FEEDER EGA RULE: Join 'feedback_data' and 'ega_details_data' on topic = machine_id and return all feeder columns with their EGA percent. "
                    "SQL template: `SELECT fd.topic, fd.rf1_amplitude, fd.rf2_amplitude, fd.rf3_amplitude, fd.rf4_amplitude, fd.rf5_amplitude, fd.rf6_amplitude, fd.rf7_amplitude, fd.rf8_amplitude, fd.rf9_amplitude, eg.ega_percent FROM feedback_data fd JOIN ega_details_data eg ON fd.topic = eg.machine_id`"
                )
                matched_tables.update({"feedback_data", "ega_details_data"})
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
        for shift_name, shift_data in self.shift_patterns.items():
            start_t = shift_data["start"]
            end_t = shift_data["end"]
            label = shift_data["label"]
            aliases = shift_data.get("aliases", [shift_name])
            if any(alias in q_lower for alias in aliases):
                # Pick correct time column based on matched tables
                time_col = "unix_timestamp"  # default
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

        # 5. Counting and Filtering Rules
        counting_keywords = ["how many", "count", "total number", "number of"]
        listing_keywords = ["list all", "show all", "give me all", "display all", "get all"]
        filtering_keywords = ["where", "with", "having", ">", "<", "=", "above", "below", "greater", "less"]
        
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
                "(e.g., 'greater than', 'above', 'below', '<', '>', '=', etc.). "
                "Instead of returning a single aggregated average or sum, you MUST write a SELECT query to list the individual "
                "records/rows matching the filter condition, including relevant identifying columns (like machine_id, loop_id, variant, start_time/timestamp) "
                "and the metric column itself. Do NOT aggregate with AVG() or SUM() for the whole table when filtering. "
                "Example for 'ega greater than 2.5': `SELECT machine_id, loop_id, variant, start_time, ega_percent FROM ega_details_data WHERE ega_percent > 2.5`"
            )

        return {
            "hints": "\n".join(hints) if hints else "No specific manufacturing templates detected.",
            "corrections": corrections
        }

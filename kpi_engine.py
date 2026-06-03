import re
import json
from pathlib import Path
from difflib import get_close_matches

# Self-contained manufacturing formulas and aggregation logic
# Aligned precisely with the public schema of the user's new 'triniti_db' database!
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
        # Handle "weigher N", "machine N", "Machine-N", etc.
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
        
        # Detect "compare" or "vs" or "versus" intent — always requires GROUP BY per entity
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
                # Pick correct time column based on matched tables
                time_col = "start_time"  # default for new tables
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
        # Detect ISO dates (YYYY-MM-DD) and generate PARSED TIME FILTER
        date_patterns = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', user_query)
        if date_patterns:
            # Pick correct time column based on matched tables
            time_col = "start_time"  # default
            for t in matched_tables:
                if t in TIME_COLUMN_MAP:
                    time_col = TIME_COLUMN_MAP[t]
                    break
            
            for date_str in date_patterns:
                hints.append(
                    f"- PARSED TIME FILTER: {time_col}::date = '{date_str}'"
                )
                # Reinforce GROUP BY requirement whenever date filtering
                hints.append(
                    f"- DATE+GROUPBY RULE: Since a date filter is applied, ALWAYS use "
                    f"GROUP BY machine_id (and machine_name if selected) so each machine "
                    f"shows its daily aggregate, not just one hourly row."
                )
                break  # Only need one date filter

        # 7. Grammage format normalization
        # User might say "10.5g", "10.5 g", "10.5 gram", or just "10.5" in context of variant
        # Database stores as NUMERIC (number) without 'g' suffix
        # Match patterns like: "10.5g", "10.5 gram", "for the 10.5 Ridge"
        grammage_patterns = re.findall(r'\b(\d+(?:\.\d+)?)\s*(?:g\b|grams?\b|(?=\s+(?:ridge|flat|variant)))', q_lower, re.IGNORECASE)
        seen_grammage = set()
        for gram_val in grammage_patterns:
            try:
                gram_num = float(gram_val)
                if gram_num > 5 and gram_num < 500 and gram_num not in seen_grammage:  # reasonable gram range
                    seen_grammage.add(gram_num)
                    hints.append(
                        f"- GRAMMAGE FORMAT: User mentioned '{gram_val}' grams. "
                        f"The grammage column is NUMERIC (stores numbers like 10.5, 20, 43, 85, 90, NOT text). "
                        f"Use: grammage = {gram_num} (as a NUMBER without quotes or 'g' suffix)"
                    )
                    break  # Only need one hint
            except ValueError:
                continue

        # 8. Availability semantic mapping
        # When user asks about "availability" or "100% availability", translate to downtime_mins
        if "availability" in q_lower or "available" in q_lower:
            if any(pattern in q_lower for pattern in ["100%", "100 percent", "full availability", "perfect availability", "maximum availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 100% availability. "
                    "This means ZERO downtime. Use: WHERE downtime_mins = 0 "
                    "(Do NOT try to calculate availability or use a non-existent 'availability' column)"
                )
            elif any(pattern in q_lower for pattern in ["0%", "zero percent", "no availability", "lowest availability"]):
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for 0% availability. "
                    "This means MAXIMUM downtime. Use: ORDER BY downtime_mins DESC "
                    "(Do NOT try to calculate availability or use a non-existent 'availability' column)"
                )
            elif "highest availability" in q_lower or "best availability" in q_lower or "most available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for highest availability. "
                    "This means LOWEST downtime. Use: ORDER BY downtime_mins ASC LIMIT 1 "
                    "(Do NOT try to calculate availability or use a non-existent 'availability' column)"
                )
            elif "lowest availability" in q_lower or "worst availability" in q_lower or "least available" in q_lower:
                hints.append(
                    "- AVAILABILITY SEMANTIC MAPPING: User asked for lowest availability. "
                    "This means HIGHEST downtime. Use: ORDER BY downtime_mins DESC LIMIT 1 "
                    "(Do NOT try to calculate availability or use a non-existent 'availability' column)"
                )
            else:
                # General availability query - provide formula
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

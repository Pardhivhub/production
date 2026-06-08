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


class ResultValidator:
    """Validates query results for impossible/corrupt values"""
    
    def validate_results(self, results: List[Dict[str, Any]], query_type: str) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
        """
        Args:
            results: List of result rows from database
            query_type: Type of query (quality, ega, downtime, etc.)
        
        Returns:
            (is_valid, warnings, filtered_results)
        """
        warnings = []
        filtered_results = results.copy()
        
        if not results:
            return True, [], []
        
        # ═══════════════════════════════════════════════════════════════
        # QUALITY PERCENTAGE VALIDATION
        # ═══════════════════════════════════════════════════════════════
        if query_type in ["quality", "quality_percentage"]:
            for row in results:
                for key, value in row.items():
                    if "quality" in key.lower() and isinstance(value, (int, float, Decimal)):
                        if value > 100:
                            warnings.append(
                                f"🚨 IMPOSSIBLE VALUE: Quality {value:.2f}% > 100% for {row}. "
                                f"Indicates corrupt data (negative bags) in database!"
                            )
                            # Filter out this row
                            filtered_results = [r for r in filtered_results if r != row]
                        elif value < 0:
                            warnings.append(
                                f"⚠️  NEGATIVE QUALITY: {value:.2f}% for {row}. Corrupt data!"
                            )
                            filtered_results = [r for r in filtered_results if r != row]
        
        # ═══════════════════════════════════════════════════════════════
        # EGA VALIDATION
        # ═══════════════════════════════════════════════════════════════
        if query_type == "ega":
            for row in results:
                for key, value in row.items():
                    if "ega" in key.lower() and isinstance(value, (int, float, Decimal)):
                        # EGA can be negative (underweight) or positive (overweight)
                        # But extremely large values (>1000%) indicate corrupt data
                        if abs(value) > 1000:
                            warnings.append(
                                f"⚠️  EXTREME EGA: {value:.2f}% for {row}. Likely corrupt data!"
                            )
        
        # ═══════════════════════════════════════════════════════════════
        # NEGATIVE COUNTS VALIDATION
        # ═══════════════════════════════════════════════════════════════
        count_columns = ["good_bags", "failed_bags", "empty_bags", "total_bags", "downtime_mins", "wastage_kg"]
        for row in results:
            for col in count_columns:
                if col in row and isinstance(row[col], (int, float, Decimal)):
                    if row[col] < 0:
                        warnings.append(
                            f"🚨 NEGATIVE COUNT: {col} = {row[col]} for {row}. Corrupt data!"
                        )
                        # Filter out this row
                        filtered_results = [r for r in filtered_results if r != row]
                        break
        
        # ═══════════════════════════════════════════════════════════════
        # AVAILABILITY > 100% VALIDATION
        # ═══════════════════════════════════════════════════════════════
        if query_type == "availability":
            for row in results:
                for key, value in row.items():
                    if "availability" in key.lower() and isinstance(value, (int, float, Decimal)):
                        if value > 100:
                            warnings.append(
                                f"🚨 IMPOSSIBLE AVAILABILITY: {value:.2f}% > 100% for {row}. "
                                f"Check run_duration and downtime_mins calculation!"
                            )
                            filtered_results = [r for r in filtered_results if r != row]
        
        # ═══════════════════════════════════════════════════════════════
        # ZERO DIVISION DETECTION
        # ═══════════════════════════════════════════════════════════════
        for row in results:
            for key, value in row.items():
                if value is None and ("percentage" in key.lower() or "percent" in key.lower() or "ratio" in key.lower()):
                    warnings.append(
                        f"⚠️  NULL PERCENTAGE: {key} is NULL for {row}. Possible division by zero!"
                    )
        
        is_valid = not any("🚨 IMPOSSIBLE" in w or "🚨 NEGATIVE" in w for w in warnings)
        
        return is_valid, warnings, filtered_results


class EntityMapper:
    """Maps natural language queries to correct database entities"""
    
    ENTITY_KEYWORDS = {
        "machine": {
            "keywords": ["machine", "weigher", "equipment", "robot", "filler", "sealer"],
            "column": "machine_id",
            "group_by": ["machine_id", "machine_name"]
        },
        "grammage": {
            "keywords": ["grammage", "weight", "gram", "size", "sku"],
            "column": "grammage",
            "group_by": ["grammage"]
        },
        "variant": {
            "keywords": ["variant", "type", "ridge", "flat", "cut", "product"],
            "column": "variant",
            "group_by": ["variant"]
        },
        "loop": {
            "keywords": ["loop", "line"],
            "column": "loop_id",
            "group_by": ["loop_id"]
        },
        "shift": {
            "keywords": ["shift", "morning", "afternoon", "night", "overnight"],
            "column": "shift",
            "group_by": ["shift"]
        },
        "plant": {
            "keywords": ["plant", "factory", "site"],
            "column": "plant_id",
            "group_by": ["plant_id"]
        }
    }
    
    def detect_primary_entity(self, user_query: str) -> Tuple[str, str, List[str]]:
        """
        Detects what entity the user is asking about.
        
        Returns:
            (entity_name, column_name, group_by_columns)
        """
        q_lower = user_query.lower()
        
        # Extract the "which X" or "what X" pattern
        which_pattern = re.search(r"which\s+(\w+)|what\s+(\w+)", q_lower)
        what_entity = None
        if which_pattern:
            what_entity = which_pattern.group(1) or which_pattern.group(2)
        
        # Score each entity based on keyword matches and position
        entity_scores = {}
        for entity, meta in self.ENTITY_KEYWORDS.items():
            score = 0
            
            # Boost score if entity appears in "which X" or "what X"
            if what_entity and any(kw in what_entity for kw in meta["keywords"]):
                score += 100
            
            # Add points for each keyword match
            for keyword in meta["keywords"]:
                if keyword in q_lower:
                    # Boost if keyword appears early in query
                    position = q_lower.find(keyword)
                    if position < 50:
                        score += 10
                    else:
                        score += 5
            
            entity_scores[entity] = score
        
        # Get highest scoring entity
        if entity_scores:
            top_entity = max(entity_scores, key=entity_scores.get)
            if entity_scores[top_entity] > 0:
                meta = self.ENTITY_KEYWORDS[top_entity]
                return top_entity, meta["column"], meta["group_by"]
        
        # Default to machine if unclear
        return "machine", "machine_id", ["machine_id", "machine_name"]
    
    def inject_entity_hint(self, user_query: str) -> str:
        """
        Generates a hint for SQL generation based on detected entity.
        """
        entity_name, column, group_by = self.detect_primary_entity(user_query)
        
        hint = (
            f"🎯 PRIMARY ENTITY DETECTED: '{entity_name.upper()}'\n"
            f"   - The user is asking WHICH {entity_name.upper()} (NOT which machine unless entity is machine)\n"
            f"   - MANDATORY: Use GROUP BY {', '.join(group_by)}\n"
            f"   - MANDATORY: Include {', '.join(group_by)} in SELECT clause\n"
            f"   - Filter by: {column}\n"
        )
        
        # Add specific warnings for common mistakes
        if entity_name == "grammage":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be grammage values like 10.5, 20, 43, etc.\n"
            )
        elif entity_name == "loop":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be loop_id values like 1, 2, 3, etc.\n"
            )
        elif entity_name == "variant":
            hint += (
                f"   ⚠️  DO NOT return machine_id or machine_name as the answer!\n"
                f"   ⚠️  The result should be variant names like 'Flat Cut', 'Ridge Cut', etc.\n"
            )
        
        return hint

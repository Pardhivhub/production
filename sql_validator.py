"""
SQL Validation Layer - Catches common LLM SQL generation errors before execution
"""
import re
from typing import Dict, List, Tuple

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
        "ega_details_data": ["machine_name"],  # exists but shouldn't be used in GROUP BY without machine_id
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
                    if "machine_id" in sql_lower and "machine_id" not in re.search(r"group by.*", sql_lower, re.IGNORECASE).group(0) if re.search(r"group by", sql_lower, re.IGNORECASE) else True:
                        # Extract existing ORDER BY and LIMIT
                        order_match = re.search(r"(ORDER BY.*?)(?:LIMIT|\Z)", sql, re.IGNORECASE | re.DOTALL)
                        order_clause = order_match.group(1).strip() if order_match else ""
                        
                        limit_match = re.search(r"(LIMIT \d+)", sql, re.IGNORECASE)
                        limit_clause = limit_match.group(1) if limit_match else ""
                        
                        # Remove existing ORDER BY and LIMIT
                        base_sql = re.sub(r"ORDER BY.*", "", sql, flags=re.IGNORECASE | re.DOTALL).strip()
                        
                        # Add GROUP BY before ORDER BY
                        corrected_sql = f"{base_sql} GROUP BY machine_id, machine_name {order_clause} {limit_clause}".strip()
                        warnings.append(f"✅ AUTO-FIX: Added 'GROUP BY machine_id, machine_name'")
        
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

# Example usage
if __name__ == "__main__":
    validator = SQLValidator()
    
    # Test case 1: Missing GROUP BY
    bad_sql = "SELECT machine_id FROM oee_details_data WHERE start_time::date = '2025-05-28' ORDER BY failed_bags DESC LIMIT 1"
    valid, warns, fixed = validator.validate(bad_sql, "Which machine had most failed bags on 2025-05-28?")
    print("Test 1 - Missing GROUP BY:")
    print(f"Valid: {valid}")
    print(f"Warnings: {warns}")
    print(f"Fixed SQL: {fixed}\n")
    
    # Test case 2: Quality without data validation
    bad_sql2 = "SELECT machine_id, (SUM(good_bags)*100)/SUM(good_bags+failed_bags) as quality FROM oee_details_data WHERE start_time::date = '2025-06-03' GROUP BY machine_id"
    valid2, warns2, fixed2 = validator.validate(bad_sql2, "Which machine had worst quality on 2025-06-03?")
    print("Test 2 - Missing data validation:")
    print(f"Valid: {valid2}")
    print(f"Warnings: {warns2}")
    print(f"Fixed SQL: {fixed2}\n")

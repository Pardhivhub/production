"""
Result Validator - Detects impossible values and data quality issues in query results
"""
from typing import List, Dict, Any, Tuple

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
        
        from decimal import Decimal
        
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

# Example usage
if __name__ == "__main__":
    validator = ResultValidator()
    
    # Test case 1: Impossible quality >100%
    bad_results = [
        {"machine_id": 10, "machine_name": "Machine-10", "quality_percentage": 148.57},
        {"machine_id": 12, "machine_name": "Machine-12", "quality_percentage": 99.71}
    ]
    
    valid, warns, filtered = validator.validate_results(bad_results, "quality")
    print("Test 1 - Impossible quality:")
    print(f"Valid: {valid}")
    print(f"Warnings: {warns}")
    print(f"Filtered: {filtered}\n")
    
    # Test case 2: Negative bags
    bad_results2 = [
        {"machine_id": 6, "total_good": -624, "total_failed": 204},
        {"machine_id": 7, "total_good": 23746, "total_failed": 72}
    ]
    
    valid2, warns2, filtered2 = validator.validate_results(bad_results2, "production")
    print("Test 2 - Negative bags:")
    print(f"Valid: {valid2}")
    print(f"Warnings: {warns2}")
    print(f"Filtered: {filtered2}\n")

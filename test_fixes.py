#!/usr/bin/env python3
"""
Test script to validate chatbot fixes for grammage format, machine_id, and filtering queries.
Run this after applying fixes to ensure everything works correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db_connector import DatabaseConnector
from sql_generator import SQLGenerator
from kpi_engine import KPIEngine
from table_selector import TableSelector
from semantic_layer import SemanticLayer
from backend.config import settings

async def test_fixes():
    print("=" * 80)
    print("DATABASE CHATBOT FIX VALIDATION TEST")
    print("=" * 80)
    
    # Initialize components
    db = DatabaseConnector(settings.DATABASE_URL)
    await db.connect()
    
    schema = await db.get_schema_metadata()
    print(f"\n✓ Connected to database with {len(schema['tables'])} tables")
    
    # Enrich schema
    semantic = SemanticLayer(db)
    enriched_schema = await semantic.enrich_schema(schema)
    
    # Initialize engines
    kpi_engine = KPIEngine(enriched_schema)
    table_selector = TableSelector(enriched_schema)
    sql_gen = SQLGenerator(db)
    
    # Test cases
    test_cases = [
        {
            "name": "Test 1: Highest EGA with grammage format (10.5g)",
            "query": "which machine had the highest EGA percent on 2025-05-29 for the 10.5g Ridge Cut variant?",
            "expected_sql_contains": ["machine_id", "grammage = '10.5g'", "ORDER BY", "ega_percent", "DESC", "LIMIT 1"],
            "should_not_contain": ["machine_name", "grammage = 10.5"]
        },
        {
            "name": "Test 2: Grammage without 'g' suffix (system should add it)",
            "query": "show EGA for 100 gram Flat Cut variant",
            "expected_sql_contains": ["grammage = '100g'", "variant = 'Flat Cut'", "ega_details_data"],
            "should_not_contain": ["grammage = 100", "flavour"]
        },
        {
            "name": "Test 3: Lowest OEE query",
            "query": "which machine had the lowest OEE on 2025-05-20?",
            "expected_sql_contains": ["machine_id", "ORDER BY", "oee", "ASC", "LIMIT 1"],
            "should_not_contain": ["machine_name"]
        },
        {
            "name": "Test 4: Filter query with threshold",
            "query": "show machines with EGA greater than 2.5",
            "expected_sql_contains": ["machine_id", "ega_percent > 2.5", "WHERE"],
            "should_not_contain": ["AVG(ega_percent)", "GROUP BY"]
        },
        {
            "name": "Test 5: Machine identification",
            "query": "what is the machine with highest wastage?",
            "expected_sql_contains": ["machine_id", "wastage", "ORDER BY", "DESC", "LIMIT 1"],
            "should_not_contain": ["machine_name"]
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'-' * 80}")
        print(f"{test['name']}")
        print(f"Query: {test['query']}")
        print(f"{'-' * 80}")
        
        try:
            # Get domain hints
            domain_info = kpi_engine.compile_domain_hints(test['query'])
            hints = domain_info['hints']
            matched_tables = domain_info['matched_tables']
            
            print(f"\n✓ Matched tables: {matched_tables}")
            
            # Select relevant tables
            selected = table_selector.select_relevant_tables(
                test['query'], 
                kpi_matched_tables=matched_tables
            )
            
            # Generate SQL
            sql = await sql_gen.generate_sql(
                test['query'],
                {"tables": selected['tables']},
                hints,
                matched_tables=matched_tables
            )
            
            print(f"\nGenerated SQL:\n{sql}")
            
            # Validate SQL
            test_passed = True
            errors = []
            
            # Check expected contents
            for expected in test['expected_sql_contains']:
                if expected.lower() not in sql.lower():
                    test_passed = False
                    errors.append(f"  ✗ Missing expected: {expected}")
            
            # Check forbidden contents
            for forbidden in test['should_not_contain']:
                if forbidden.lower() in sql.lower():
                    test_passed = False
                    errors.append(f"  ✗ Contains forbidden: {forbidden}")
            
            if test_passed:
                print(f"\n✓ TEST PASSED")
                passed += 1
            else:
                print(f"\n✗ TEST FAILED")
                for error in errors:
                    print(error)
                failed += 1
                
        except Exception as e:
            print(f"\n✗ TEST FAILED WITH ERROR: {str(e)}")
            failed += 1
    
    # Summary
    print("\n" + "=" * 80)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("=" * 80)
    
    if failed == 0:
        print("\n✓ ALL TESTS PASSED! The fixes are working correctly.")
    else:
        print(f"\n✗ {failed} test(s) failed. Review the output above for details.")
    
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(test_fixes())
    sys.exit(0 if success else 1)

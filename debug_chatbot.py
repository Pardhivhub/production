#!/usr/bin/env python3
"""
Debug script to diagnose chatbot issues with specific queries.
Run this when you encounter problems to see what's happening internally.
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

async def debug_query(query: str):
    """Debug a specific query to see internal state."""
    print("=" * 80)
    print(f"DEBUGGING QUERY: {query}")
    print("=" * 80)
    
    try:
        # Initialize components
        db = DatabaseConnector(settings.DATABASE_URL)
        await db.connect()
        
        schema = await db.get_schema_metadata()
        print(f"\n1. ✅ Connected to database with {len(schema['tables'])} tables")
        
        # Enrich schema
        semantic = SemanticLayer(db)
        enriched_schema = await semantic.enrich_schema(schema)
        
        # Initialize engines
        kpi_engine = KPIEngine(enriched_schema)
        table_selector = TableSelector(enriched_schema)
        sql_gen = SQLGenerator(db)
        
        # Step 1: KPI Engine analysis
        print("\n2. 🔍 KPI ENGINE ANALYSIS")
        print("-" * 40)
        domain_info = kpi_engine.compile_domain_hints(query)
        print(f"Hints generated: {len(domain_info['hints'].split('\\n')) if domain_info['hints'] else 0}")
        print(f"Matched tables: {domain_info['matched_tables']}")
        print(f"Corrections: {domain_info['corrections']}")
        
        if domain_info['hints']:
            print(f"\nDomain hints:\\n{domain_info['hints']}")
        
        # Step 2: Table selection
        print("\n3. 📊 TABLE SELECTION")
        print("-" * 40)
        selected = table_selector.select_relevant_tables(
            query,
            kpi_matched_tables=domain_info['matched_tables']
        )
        
        print(f"Selected tables ({len(selected['tables'])}):")
        for table in selected['tables']:
            print(f"  - {table['name']}")
            columns = [c['name'] for c in table['columns'][:5]]
            if len(columns) > 0:
                print(f"    Columns (first 5): {', '.join(columns)}")
        
        # Step 3: SQL Generation
        print("\n4. ⚙️ SQL GENERATION")
        print("-" * 40)
        
        # Show what the LLM will see
        schema_sample = {}
        for table in selected['tables']:
            schema_sample[table['name']] = {
                "columns": [{"name": c['name'], "type": c.get('type', 'unknown')} 
                           for c in table['columns']],
                "samples": table.get('samples', [])[:2]  # First 2 samples
            }
        
        print(f"Schema sent to LLM (simplified):")
        for table_name, table_info in schema_sample.items():
            print(f"\n  Table: {table_name}")
            cols = [f"{c['name']} ({c['type']})" for c in table_info['columns'][:8]]
            print(f"  Columns: {', '.join(cols)}")
            if table_info['samples']:
                print(f"  Sample rows: {table_info['samples']}")
        
        # Try to generate SQL
        try:
            sql = await sql_gen.generate_sql(
                query,
                {"tables": selected['tables']},
                domain_info['hints'],
                matched_tables=domain_info['matched_tables']
            )
            
            print(f"\n✅ Generated SQL:\\n{sql}")
            
            # Validate SQL
            print(f"\n5. ✅ VALIDATION")
            print("-" * 40)
            try:
                result = await db.execute_query(sql)
                print(f"Query executed successfully!")
                print(f"Rows returned: {result['row_count']}")
                if result['row_count'] > 0:
                    print(f"Columns: {result['columns']}")
                    if result['row_count'] <= 3:
                        print(f"Sample results: {result['rows']}")
                    else:
                        print(f"First 3 results: {result['rows'][:3]}")
                else:
                    print("⚠️ No rows returned (empty result)")
            except Exception as e:
                print(f"❌ SQL Execution failed: {str(e)}")
                print(f"SQL that failed: {sql}")
                
        except Exception as e:
            print(f"\n❌ SQL Generation failed: {str(e)}")
            
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("DEBUG COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 debug_chatbot.py \"your query here\"")
        print("\nExample:")
        print('  python3 debug_chatbot.py "which machine had the highest EGA percent on 2025-05-29 for the 10.5g Ridge Cut variant?"')
        sys.exit(1)
    
    query = sys.argv[1]
    asyncio.run(debug_query(query))

import asyncio
import logging
from database import DatabaseConnector
from sql_generation import SQLGenerator
from backend.config import settings

logging.basicConfig(level=logging.INFO)

async def test_dynamic_prompt():
    print("Initializing DatabaseConnector...")
    db = DatabaseConnector(settings.DATABASE_URL)
    # Connect
    await db.connect()
    
    print("\nInitializing SQLGenerator...")
    generator = SQLGenerator(db)
    
    # We can fetch schema info
    from database import SemanticLayer
    semantic_layer = SemanticLayer(db)
    raw_schema = await db.get_schema_metadata()
    schema_info = await semantic_layer.enrich_schema(raw_schema)
    
    queries = [
        "Which machine had the highest downtime on 2025-05-28?",
        "What is the average excess giveaway for 10.5g grammage?",
        "Which line in Plant 1 had the highest wastage on 2025-06-01?"
    ]
    
    for query in queries:
        print(f"\n==========================================")
        print(f"Testing Query: {query}")
        print(f"==========================================")
        
        # Test get_relevant_prompt_context directly first
        rules, examples = generator.prompt_rag.get_relevant_prompt_context(query)
        print("--- RETRIEVED RULES ---")
        print(rules if rules else "[No rules retrieved]")
        print("\n--- RETRIEVED EXAMPLES ---")
        print(examples if examples else "[No examples retrieved]")
        print("------------------------")
        
        # Test full generation
        sql = await generator.generate_sql(
            query=query,
            schema_info=schema_info,
            domain_hints="No hints.",
            max_retries=1
        )
        print(f"\nGENERATED SQL:\n{sql}")
        
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(test_dynamic_prompt())

import asyncio
import os
import json
from dotenv import load_dotenv
from database import DatabaseConnector

load_dotenv()
db_url = os.getenv("DATABASE_URL")

async def main():
    db = DatabaseConnector(db_url)
    await db.connect()
    schema = await db.get_schema_metadata()
    
    # Format and print the schema in Markdown
    print("# Database Schema Overview")
    print(f"Connected database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print()
    
    for table in schema.get("tables", []):
        print(f"## Table: `{table['name']}` (Rows: {table['row_count']})")
        print("| Column Name | Data Type |")
        print("| --- | --- |")
        for col in table["columns"]:
            print(f"| `{col['name']}` | {col['type']} |")
        print()
        if table["samples"]:
            print("### Sample Data:")
            print("```json")
            print(json.dumps(table["samples"], indent=2))
            print("```")
            print()
        print("---")
        print()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
from dotenv import load_dotenv
from database import DatabaseConnector

load_dotenv()
db_url = os.getenv("DATABASE_URL")

async def main():
    db = DatabaseConnector(db_url)
    await db.connect()
    
    # Try the natural-looking query for highest EGA on Machine 12 on 2025-06-03
    q = """
        SELECT 
            variant, 
            loop_id, 
            AVG(ega_percent) AS avg_ega
        FROM ega_details_data
        WHERE start_time::date = '2025-06-03' AND machine_id = 12
        GROUP BY variant, loop_id
        ORDER BY avg_ega DESC
        LIMIT 1;
    """
    try:
        res = await db.execute_query(q)
        print("Query successful!")
        for row in res["rows"]:
            print(row)
    except Exception as e:
        print(f"Query failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())

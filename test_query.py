xlimport asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from backend.config import settings

async def main():
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://")
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        q2 = """
        SELECT ega_percent, start_time
        FROM ega_details_data
        WHERE start_time::date BETWEEN '2025-05-01' AND '2025-05-31'
          AND machine_id = 4
        LIMIT 5;
        """
        res2 = await conn.execute(text(q2))
        raw_rows = [dict(r._mapping) for r in res2.fetchall()]
        print("Raw ega_percent samples:", raw_rows)
        
        q_avg = """
        SELECT AVG(ega_percent)
        FROM ega_details_data
        WHERE start_time::date BETWEEN '2025-05-01' AND '2025-05-31'
          AND machine_id = 4;
        """
        res_avg = await conn.execute(text(q_avg))
        avg_row = res_avg.fetchone()
        print("Average ega_percent:", avg_row[0])
        
if __name__ == "__main__":
    asyncio.run(main())

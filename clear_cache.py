import asyncio
from backend.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def clear():
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://")
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        try:
            await conn.execute(text("TRUNCATE TABLE semantic_query_cache"))
            await conn.commit()
            print("DB cache cleared!")
        except Exception as e:
            print(f"Failed to clear DB cache (might not exist): {e}")

if __name__ == "__main__":
    asyncio.run(clear())

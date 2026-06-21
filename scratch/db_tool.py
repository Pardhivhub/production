import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from backend.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://'))
    async with engine.connect() as conn:
        # Clear semantic cache
        await conn.execute(text("TRUNCATE TABLE semantic_query_cache;"))
        await conn.commit()
        print("Semantic cache cleared.")

        # Check columns of wastage_reasons
        res = await conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'wastage_reasons'"))
        print("\nwastage_reasons columns:")
        for r in res.fetchall():
            print(f"- {r[0]} ({r[1]})")

        # Check columns of oee_details_data
        res = await conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'oee_details_data'"))
        print("\noee_details_data columns:")
        cols = [r[0] for r in res.fetchall()]
        print(", ".join(cols))

asyncio.run(main())

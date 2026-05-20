import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

logger = logging.getLogger(__name__)

class DatabaseConnector:
    def __init__(self, db_url: str):
        # Format the SQLite or Postgres URL for async drivers
        if db_url.startswith("sqlite"):
            if not db_url.startswith("sqlite+aiosqlite://"):
                if db_url.startswith("sqlite:///"):
                    self.db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
                else:
                    self.db_url = f"sqlite+aiosqlite:///{db_url}"
            else:
                self.db_url = db_url
        elif db_url.startswith("postgresql") or db_url.startswith("postgres"):
            if not db_url.startswith("postgresql+asyncpg://"):
                self.db_url = db_url.replace("postgresql://", "postgresql+asyncpg://").replace("postgres://", "postgresql+asyncpg://")
            else:
                self.db_url = db_url
        else:
            raise ValueError("Unsupported database type. Please use SQLite or PostgreSQL URL.")
            
        self.engine: AsyncEngine = None

    async def connect(self):
        try:
            logger.info(f"Connecting to database via URL: {self.db_url}")
            self.engine = create_async_engine(self.db_url)
            # Verify the connection instantly
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Successfully connected to the database.")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise e

    async def execute_query(self, sql_query: str) -> dict:
        if not self.engine:
            raise RuntimeError("Database not connected. Please connect first.")
            
        # Enforce read-only safety guardrail
        lower_query = sql_query.lower()
        destructive_keywords = {"drop", "delete", "truncate", "update", "insert", "alter", "create"}
        if any(keyword in lower_query for keyword in destructive_keywords):
            raise ValueError("Destructive write operations are strictly blocked for security.")

        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(text(sql_query))
                
                # If query returns rows
                if result.returns_rows:
                    columns = list(result.keys())
                    rows = []
                    for row in result.all():
                        # Map row values to columns and serialize decimals
                        row_dict = {}
                        for col, val in zip(columns, row):
                            # Convert decimal and datetime values for JSON serialization
                            if hasattr(val, "quantize") or type(val).__name__ == "Decimal":
                                row_dict[col] = float(val)
                            elif hasattr(val, "isoformat"):
                                row_dict[col] = val.isoformat()
                            else:
                                row_dict[col] = val
                        rows.append(row_dict)
                        
                    return {
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows)
                    }
                else:
                    return {
                        "columns": [],
                        "rows": [],
                        "row_count": 0
                    }
        except Exception as e:
            logger.error(f"Failed to execute SQL: {sql_query}. Error: {e}")
            raise e

    async def get_schema_metadata(self) -> dict:
        """Retrieves raw tables and columns to populate the schema and guide the AI."""
        if not self.engine:
            raise RuntimeError("Database not connected. Please connect first.")
            
        tables = []
        try:
            async with self.engine.connect() as conn:
                # Retrieve tables list depending on dialect
                dialect = self.engine.dialect.name
                if dialect == "sqlite":
                    query_tables = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
                else:  # Postgres
                    query_tables = "SELECT table_name FROM information_schema.tables WHERE table_schema IN ('public', 'itciot');"
                
                res_tables = await conn.execute(text(query_tables))
                table_names = [r[0] for r in res_tables.all()]
                
                # Retrieve column info for each table
                for table in table_names:
                    columns = []
                    if dialect == "sqlite":
                        res_cols = await conn.execute(text(f"PRAGMA table_info({table});"))
                        for r in res_cols.all():
                            columns.append({"name": r[1], "type": r[2]})
                    else:  # Postgres
                        res_cols = await conn.execute(text(
                            f"SELECT column_name, data_type FROM information_schema.columns "
                            f"WHERE table_schema IN ('public', 'itciot') AND table_name='{table}';"
                        ))
                        for r in res_cols.all():
                            columns.append({"name": r[0], "type": r[1]})
                            
                    # Retrieve sample rows (up to 3) for better LLM context
                    sample_rows = []
                    try:
                        sample_res = await conn.execute(text(f"SELECT * FROM {table} LIMIT 3;"))
                        rows = sample_res.all()
                        col_names = [c for c in sample_res.keys()]
                        for row in rows:
                            row_dict = {}
                            for col, val in zip(col_names, row):
                                if hasattr(val, "quantize") or type(val).__name__ == "Decimal":
                                    row_dict[col] = float(val)
                                elif hasattr(val, "isoformat"):
                                    row_dict[col] = val.isoformat()
                                else:
                                    row_dict[col] = val
                            sample_rows.append(row_dict)
                    except Exception:
                        sample_rows = []
                    
                    # Retrieve the row count for the table
                    row_count = 0
                    try:
                        count_res = await conn.execute(text(f"SELECT COUNT(*) FROM {table};"))
                        row_count = count_res.scalar()
                    except Exception:
                        row_count = 0
                        
                    tables.append({
                        "name": table,
                        "columns": columns,
                        "samples": sample_rows,
                        "row_count": row_count
                    })
            return {"tables": tables}
        except Exception as e:
            logger.error(f"Failed to extract schema: {e}")
            raise e

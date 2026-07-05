import pandas as pd
from sqlalchemy import create_engine
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DB_URL = "postgresql://pardhivkrishna@localhost:5432/triniti_db"

def load_data():
    try:
        engine = create_engine(DB_URL)
        
        files_to_tables = {
            "/Users/pardhivkrishna/Downloads/Ega Data": "ega_details_data",
            "/Users/pardhivkrishna/Downloads/Oee Data": "oee_details_data",
            "/Users/pardhivkrishna/Downloads/wastage records": "wastage_records",
            "/Users/pardhivkrishna/Downloads/Production speed": "production_speed_details_data"
        }
        
        for file_path, table_name in files_to_tables.items():
            logging.info(f"Loading {file_path} into {table_name}...")
            
            # Read CSV
            df = pd.read_csv(file_path)
            
            # For JSONB column, ensure it's a string representation of json
            if table_name == 'production_speed_details_data':
                if 'production_speed_bpm' in df.columns:
                    # sometimes pandas reads it as object, just keep it as string
                    df['production_speed_bpm'] = df['production_speed_bpm'].apply(
                        lambda x: json.dumps(x) if isinstance(x, (list, dict)) else str(x)
                    )
            
            # Insert into database
            rows = df.to_sql(table_name, engine, if_exists='append', index=False, chunksize=5000, method='multi')
            logging.info(f"Successfully inserted {len(df)} rows into {table_name}.")

    except Exception as e:
        logging.error(f"Error loading data: {e}")
        sys.exit(1)

if __name__ == "__main__":
    load_data()

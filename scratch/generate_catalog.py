import asyncio
import os
from db_connector import DatabaseConnector
from sqlalchemy import text

async def main():
    db = DatabaseConnector('postgresql://pardhivkrishna@localhost:5432/iiot_feedback')
    await db.connect()
    meta = await db.get_schema_metadata()
    
    markdown_lines = [
        '# 🗄️ Database Contents & Schema Catalog',
        'This document provides a complete inventory and row preview for all active tables in the `iiot_feedback` database.',
        ''
    ]
    
    # Sort tables by name for clean reading
    tables = sorted(meta.get('tables', []), key=lambda x: x['name'])
    
    for tbl in tables:
        name = tbl['name']
        row_count = tbl.get('row_count', 0)
        status = f'({row_count:,} rows)' if row_count > 0 else '(0 rows - EMPTY)'
        
        markdown_lines.append(f'## 📋 Table: `{name}` {status}')
        
        # Columns table
        markdown_lines.append('| Column Name | Data Type |')
        markdown_lines.append('| --- | --- |')
        for col in tbl.get('columns', []):
            markdown_lines.append(f'| `{col["name"]}` | *{col["type"]}.* |')
        markdown_lines.append('')
        
        # Rows preview
        samples = tbl.get('samples', [])
        if samples:
            markdown_lines.append('### 🔍 Sample Rows Preview (Up to 3 rows)')
            # Build keys
            keys = list(samples[0].keys())
            markdown_lines.append('| ' + ' | '.join([f'**{k}**' for k in keys]) + ' |')
            markdown_lines.append('| ' + ' | '.join(['---' for _ in keys]) + ' |')
            for row in samples:
                row_vals = []
                for k in keys:
                    v = row[k]
                    if v is None:
                        row_vals.append('*NULL*')
                    elif isinstance(v, (int, float)):
                        row_vals.append(str(v))
                    else:
                        # Truncate long strings for clean rendering
                        val_str = str(v)
                        if len(val_str) > 40:
                            val_str = val_str[:37] + '...'
                        row_vals.append(val_str)
                markdown_lines.append('| ' + ' | '.join(row_vals) + ' |')
        else:
            markdown_lines.append('> ⚠️ *No rows present in this table.*')
            
        markdown_lines.append('')
        markdown_lines.append('---')
        markdown_lines.append('')
        
    os.makedirs('artifacts', exist_ok=True)
    with open('artifacts/database_contents.md', 'w') as f:
        f.write('\n'.join(markdown_lines))
    print('Markdown catalog created successfully!')

if __name__ == '__main__':
    asyncio.run(main())

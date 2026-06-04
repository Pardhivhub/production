import requests
import json

url = "http://localhost:8000/chat"

queries = [
    "What was the total downtime (in minutes) for all machines in \"Plant 2 (East Rickychester)\" on 2025-05-28?",
    "Find the top 3 machines by total failed bags on 2025-05-28, showing their actual machine names from the machines table."
]

for q in queries:
    print(f"\nQ: {q}")
    try:
        response = requests.post(url, json={"query": q})
        data = response.json()
        print(f"SQL: {data.get('sql', 'None')}")
        tables = [t['name'] for t in data.get('tables', [])] if isinstance(data.get('tables'), list) else data.get('tables', [])
        print(f"Tables: {', '.join(tables)}")
    except Exception as e:
        print(f"Error: {e}")

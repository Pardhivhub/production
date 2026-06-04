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
        response = requests.post(url, json={"query": q}, stream=True)
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data: '):
                    data = json.loads(decoded_line[6:])
                    if 'sql' in data:
                        print(f"SQL: {data['sql']}")
                    if 'answer' in data:
                        print(f"Answer: {data['answer'][:100]}...")
    except Exception as e:
        print(f"Error: {e}")

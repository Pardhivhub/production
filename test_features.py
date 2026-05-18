#!/usr/bin/env python3
"""
Test the advanced features directly
"""

import asyncio
import aiohttp
import json

async def test_advanced_features():
    base_url = "http://localhost:8000"
    
    async with aiohttp.ClientSession() as session:
        # Test 1: Basic query with suggestions
        print("🔍 Test 1: Basic query with suggestions")
        print("Query: 'What is the average actual weight?'")
        
        async with session.post(
            f"{base_url}/chat",
            json={"query": "What is the average actual weight?", "session_id": "test1"}
        ) as response:
            
            if response.status == 200:
                response_text = await response.text()
                print("\nRaw SSE Response:")
                print("-" * 50)
                print(response_text[:1000])
                print("-" * 50)
                
                # Parse events
                events = []
                lines = response_text.strip().split('\n')
                current_event = {}
                for line in lines:
                    if line.startswith('event:'):
                        if current_event:
                            events.append(current_event)
                        current_event = {'type': line[6:].strip()}
                    elif line.startswith('data:'):
                        try:
                            data = json.loads(line[5:].strip())
                            current_event['data'] = data
                        except:
                            current_event['raw_data'] = line[5:].strip()
                
                if current_event:
                    events.append(current_event)
                
                print("\nParsed Events:")
                for event in events:
                    print(f"\nEvent Type: {event.get('type')}")
                    if 'data' in event:
                        print(f"Data: {json.dumps(event['data'], indent=2)[:500]}...")
                        
                        # Check for suggestions
                        if event.get('type') == 'answer' and 'data' in event:
                            data = event['data']
                            if 'suggestions' in data:
                                print(f"\n✅ SUGGESTIONS FOUND: {data['suggestions']}")
                            else:
                                print(f"\n❌ No suggestions in response")
                            
                            # Check for analytics insights
                            if 'answer' in data:
                                answer = data['answer']
                                if '🔍 Automatic Insights:' in answer or '📈 Trend Alert:' in answer:
                                    print(f"\n✅ ANALYTICS INSIGHTS FOUND in answer")
                                else:
                                    print(f"\n❌ No analytics insights in answer")
            else:
                print(f"❌ HTTP Error: {response.status}")

if __name__ == "__main__":
    asyncio.run(test_advanced_features())

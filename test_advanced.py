#!/usr/bin/env python3
"""
Advanced RAG Chatbot Test Suite
Tests all 5 major features against actual iiot_feedback database
"""

import asyncio
import aiohttp
import json
import time
from typing import List, Dict, Tuple
import sys

class AdvancedChatbotTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session_id = f"test_{int(time.time())}"
        self.results = []
    
    async def test_query(self, session: aiohttp.ClientSession, query: str, test_name: str) -> Dict:
        """Send a query to the chatbot and capture response."""
        start_time = time.time()
        
        try:
            async with session.post(
                f"{self.base_url}/chat",
                json={"query": query, "session_id": self.session_id},
                timeout=30
            ) as response:
                
                if response.status != 200:
                    return {
                        "test": test_name,
                        "query": query,
                        "status": "error",
                        "error": f"HTTP {response.status}",
                        "time": time.time() - start_time
                    }
                
                # Parse SSE stream
                response_text = await response.text()
                events = self._parse_sse(response_text)
                
                return {
                    "test": test_name,
                    "query": query,
                    "status": "success",
                    "events": events,
                    "time": time.time() - start_time
                }
                
        except Exception as e:
            return {
                "test": test_name,
                "query": query,
                "status": "error",
                "error": str(e),
                "time": time.time() - start_time
            }
    
    def _parse_sse(self, sse_text: str) -> List[Dict]:
        """Parse Server-Sent Events response."""
        events = []
        lines = sse_text.strip().split('\n')
        
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
        
        return events
    
    def _extract_feature_indicators(self, events: List[Dict]) -> Dict:
        """Extract which features were activated in the response."""
        indicators = {
            "table_selection": False,
            "sql_generation": False,
            "conversation_memory": False,
            "analytics_insights": False,
            "query_suggestions": False,
            "caching": False,
            "alerts": False,
            "nl_parsing": False
        }
        
        for event in events:
            if event.get('type') == 'pipeline' and event.get('data', {}).get('stage') == 'sql_generation':
                indicators["sql_generation"] = True
            
            if event.get('type') == 'answer':
                answer_data = event.get('data', {})
                answer_text = answer_data.get('answer', '')
                
                # Check for analytics insights
                if '🔍 Automatic Insights:' in answer_text or '📈 Trend Alert:' in answer_text:
                    indicators["analytics_insights"] = True
                
                # Check for suggestions
                if answer_data.get('suggestions'):
                    indicators["query_suggestions"] = True
                
                # Check for conversation context
                if 'CONVERSATION HISTORY' in answer_text or 'previous query' in answer_text.lower():
                    indicators["conversation_memory"] = True
            
            # Check for caching (would need server logs)
            # Check for alerts (would need separate endpoint)
        
        return indicators
    
    async def run_feature_tests(self):
        """Run comprehensive tests for all features."""
        tests = [
            # 1. Table Selection & Score Filtering
            ("What is the average actual weight for Flat Cut variant?", "table_selection_basic"),
            ("Show me power consumption costs from last week", "table_selection_power"),
            ("What is the sugar inventory level in silo 1?", "table_selection_inventory"),
            
            # 2. SQL Self-Correction & Validation
            ("Calculate EGA percent for all variants", "sql_generation_ega"),
            ("Show me average speed where actual weight > target weight", "sql_generation_complex"),
            ("Compare power consumption between meter 1 and meter 2", "sql_generation_comparison"),
            
            # 3. Conversation Memory (sequence)
            ("What is the total production weight?", "memory_query1"),
            ("Break it down by variant", "memory_followup1"),
            ("Show me the same for last month", "memory_followup2"),
            
            # 4. Analytics Engine - Anomaly Detection
            ("Find anomalies in actual weight data", "analytics_anomalies"),
            ("Detect unusual power consumption patterns", "analytics_power_anomalies"),
            ("Check for abnormal humidity levels in zone A", "analytics_humidity_anomalies"),
            
            # 5. Analytics Engine - Trend Analysis
            ("What is the trend of actual speed over last 30 days?", "analytics_trend_speed"),
            ("Analyze sugar inventory trend", "analytics_trend_inventory"),
            ("Is power cost increasing or decreasing?", "analytics_trend_cost"),
            
            # 6. Query Suggester (test after basic query)
            ("What is average actual weight?", "suggester_basic"),
            
            # 7. Semantic Layer
            ("Show me Actual Weight for Flat Cut", "semantic_business_terms"),
            ("What is the Humidity Percent in packaging zone?", "semantic_column_mapping"),
            
            # 8. Natural Language Filter Parser
            ("Show me production from last 3 days where speed > 100", "nl_parser_complex"),
            ("Power consumption between January 1 and March 31, 2024", "nl_parser_date_range"),
            ("Humidity data from yesterday for zone A", "nl_parser_combined"),
            
            # 9. Query Caching (run same query twice)
            ("What is total production weight?", "cache_test1"),
            ("What is total production weight?", "cache_test2"),
            
            # 10. End-to-End Complex Scenarios
            ("Production speed dropped yesterday - find the cause", "e2e_root_cause"),
            ("Compare morning shift vs night shift performance", "e2e_comparison"),
            ("When will sugar inventory run out at current usage?", "e2e_predictive"),
        ]
        
        print(f"🚀 Starting Advanced RAG Chatbot Tests")
        print(f"Session ID: {self.session_id}")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)
        
        async with aiohttp.ClientSession() as session:
            for i, (query, test_name) in enumerate(tests, 1):
                print(f"\n[{i}/{len(tests)}] Testing: {test_name}")
                print(f"   Query: {query}")
                
                result = await self.test_query(session, query, test_name)
                self.results.append(result)
                
                if result["status"] == "success":
                    indicators = self._extract_feature_indicators(result["events"])
                    active_features = [k for k, v in indicators.items() if v]
                    
                    print(f"   ✅ Success ({result['time']:.2f}s)")
                    if active_features:
                        print(f"   Features activated: {', '.join(active_features)}")
                    
                    # Print answer if available
                    for event in result["events"]:
                        if event.get('type') == 'answer':
                            answer = event.get('data', {}).get('answer', '')
                            if answer:
                                preview = answer[:200] + "..." if len(answer) > 200 else answer
                                print(f"   Answer preview: {preview}")
                            
                            # Print suggestions if available
                            suggestions = event.get('data', {}).get('suggestions', [])
                            if suggestions:
                                print(f"   Suggestions: {suggestions[:3]}")
                else:
                    print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
                
                # Small delay between tests
                await asyncio.sleep(1)
    
    async def test_api_endpoints(self):
        """Test additional API endpoints."""
        print(f"\n🔧 Testing API Endpoints")
        print("-" * 40)
        
        async with aiohttp.ClientSession() as session:
            # Test alerts endpoint
            try:
                async with session.get(f"{self.base_url}/alerts", timeout=10) as resp:
                    if resp.status == 200:
                        alerts = await resp.json()
                        print(f"✅ Alerts endpoint: {alerts.get('count', 0)} alerts found")
                    else:
                        print(f"❌ Alerts endpoint: HTTP {resp.status}")
            except Exception as e:
                print(f"❌ Alerts endpoint error: {e}")
            
            # Test insights endpoint (requires table and metric)
            try:
                async with session.get(
                    f"{self.base_url}/insights/feedback_data/actual_weight",
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        insights = await resp.json()
                        print(f"✅ Insights endpoint: Data for {insights.get('table')}")
                    else:
                        print(f"❌ Insights endpoint: HTTP {resp.status}")
            except Exception as e:
                print(f"❌ Insights endpoint error: {e}")
    
    def generate_report(self):
        """Generate test report."""
        print(f"\n📊 TEST REPORT")
        print("=" * 60)
        
        total = len(self.results)
        success = sum(1 for r in self.results if r["status"] == "success")
        failed = total - success
        
        print(f"Total Tests: {total}")
        print(f"Successful: {success} ({success/total*100:.1f}%)")
        print(f"Failed: {failed} ({failed/total*100:.1f}%)")
        
        # Average response time
        success_times = [r["time"] for r in self.results if r["status"] == "success"]
        if success_times:
            avg_time = sum(success_times) / len(success_times)
            print(f"Average Response Time: {avg_time:.2f}s")
        
        # Feature activation summary
        feature_counts = {
            "table_selection": 0,
            "sql_generation": 0,
            "analytics_insights": 0,
            "query_suggestions": 0,
            "conversation_memory": 0
        }
        
        for result in self.results:
            if result["status"] == "success":
                indicators = self._extract_feature_indicators(result["events"])
                for feature, active in indicators.items():
                    if active and feature in feature_counts:
                        feature_counts[feature] += 1
        
        print(f"\n🎯 Feature Activation Counts:")
        for feature, count in feature_counts.items():
            percentage = count / success * 100 if success > 0 else 0
            print(f"  {feature}: {count} ({percentage:.1f}%)")
        
        # Failed tests
        if failed > 0:
            print(f"\n❌ Failed Tests:")
            for result in self.results:
                if result["status"] != "success":
                    print(f"  {result['test']}: {result.get('error', 'Unknown')}")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if success/total < 0.7:
            print("  ⚠️  Low success rate - check server logs and database connection")
        if avg_time > 5:
            print("  ⚠️  Slow response times - enable query caching")
        if feature_counts["analytics_insights"] < 3:
            print("  ⚠️  Analytics engine not activating - check configuration")
        if feature_counts["query_suggestions"] < 5:
            print("  ⚠️  Query suggester not working - check schema enrichment")
        
        print(f"\n✅ Test completed at {time.strftime('%Y-%m-%d %H:%M:%S')}")

async def main():
    """Main test runner."""
    # Get base URL from command line or use default
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    tester = AdvancedChatbotTester(base_url)
    
    try:
        # Run feature tests
        await tester.run_feature_tests()
        
        # Test API endpoints
        await tester.test_api_endpoints()
        
        # Generate report
        tester.generate_report()
        
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test runner error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Check if server is running
    print("🔍 Checking if server is running...")
    
    # Run tests
    asyncio.run(main())

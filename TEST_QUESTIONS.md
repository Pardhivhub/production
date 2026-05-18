# TEST QUESTIONS FOR ADVANCED RAG CHATBOT
# Based on actual iiot_feedback database schema

## 📊 Database Schema Summary:
- **feedback_data**: 16,420 rows - Production feedback (weight, speed, variants)
- **electric_meter_hourly**: Power consumption and costs
- **sugar_silo_levels**: Inventory tracking
- **factory_humidity_logs**: Environmental monitoring
- **golden_settings**: Target specifications
- **b2b_client_orders**: Customer orders
- **packaging_inventory**: Packaging materials
- **shift_assignments**: Work shift data

## 🧪 TEST QUESTIONS BY FEATURE

### 1. **Table Selection & Score Filtering**
_Test: embedder.py, table_selector.py_

**Questions:**
1. "What is the average actual weight for Flat Cut variant?"
   - Should select: `feedback_data` only
   - Should filter out: other tables (electric_meter, silo_levels, etc.)

2. "Show me power consumption costs from last week"
   - Should select: `electric_meter_hourly` only
   - Score should filter out unrelated tables

3. "What is the sugar inventory level in silo 1?"
   - Should select: `sugar_silo_levels` only
   - Test distance threshold filtering

### 2. **SQL Self-Correction & Validation**
_Test: sql_generator.py_

**Questions:**
4. "Calculate EGA percent for all variants"
   - Should generate: `((SUM(actual_weight) - SUM(target_weight)) / NULLIF(SUM(actual_weight), 0)) * 100`
   - Should validate with EXPLAIN before returning

5. "Show me average speed where actual weight > target weight"
   - Complex WHERE clause
   - Should retry if initial SQL fails validation

6. "Compare power consumption between meter 1 and meter 2"
   - Multi-table/column comparison
   - Test self-correction loop

### 3. **Conversation Memory**
_Test: conversation_memory.py_

**Sequence Test:**
7. **First query:** "What is the total production weight?"
8. **Follow-up:** "Break it down by variant"
   - Should use context from query 7
   - Should understand "it" refers to production weight

9. **Follow-up:** "Show me the same for last month"
   - Should maintain context of metric and breakdown
   - Should apply temporal filter correctly

### 4. **Analytics Engine - Anomaly Detection**
_Test: analytics_engine.py_

**Questions:**
10. "Find anomalies in actual weight data"
    - Should run Z-score analysis
    - Return outliers with deviation percentages

11. "Detect unusual power consumption patterns"
    - Should analyze `electric_meter_hourly.kwh_consumed`
    - Return anomalies with timestamps

12. "Check for abnormal humidity levels in zone A"
    - Should analyze `factory_humidity_logs.humidity_pct`
    - Return statistical outliers

### 5. **Analytics Engine - Trend Analysis**
_Test: analytics_engine.py_

**Questions:**
13. "What is the trend of actual speed over last 30 days?"
    - Should calculate linear regression slope
    - Return direction (increasing/decreasing/stable)

14. "Analyze sugar inventory trend"
    - Should detect if inventory is depleting/accumulating
    - Return forecast for next reading

15. "Is power cost increasing or decreasing?"
    - Should analyze `electric_meter_hourly.cost` trend
    - Return change percentage

### 6. **Analytics Engine - Correlation Discovery**
_Test: analytics_engine.py_

**Questions:**
16. "Find correlations between actual weight and actual speed"
    - Should calculate Pearson correlation
    - Return strength (strong/moderate/weak)

17. "Do humidity levels correlate with production speed?"
    - Cross-table correlation analysis
    - Should join `feedback_data` and `factory_humidity_logs`

### 7. **Query Suggester**
_Test: query_suggester.py_

**Test Scenarios:**
18. **After query:** "What is average actual weight?"
    - **Should suggest:**
      - "Break down by variant"
      - "Show me the trend over time"
      - "Compare with target weight"
      - "Find anomalies in weight data"

19. **After query:** "Show me power consumption"
    - **Should suggest:**
      - "Break down by meter"
      - "Calculate total cost"
      - "Find peak demand hours"
      - "Compare this week vs last week"

20. **After query:** "What is sugar inventory?"
    - **Should suggest:**
      - "Break down by silo number"
      - "Show me temperature readings"
      - "Find when inventory is lowest"
      - "Calculate depletion rate"

### 8. **Semantic Layer**
_Test: semantic_layer.py_

**Questions using business terms:**
21. "Show me Actual Weight for Flat Cut"
    - Should map "Actual Weight" → `actual_weight`
    - Should use business-friendly column names

22. "What is the Humidity Percent in packaging zone?"
    - Should map "Humidity Percent" → `humidity_pct`
    - Should understand "packaging zone" context

23. "Calculate Excess Give Away percentage"
    - Should use EGA formula from KPI catalog
    - Should understand business terminology

### 9. **Alert System**
_Test: alert_system.py_

**Questions to trigger alerts:**
24. "Check for high EGA alerts in last hour"
    - Should run EGA calculation
    - Trigger alert if >5%

25. "Are there any zero production records today?"
    - Should check `actual_weight = 0`
    - Trigger alert if multiple zero records

26. "Is sugar inventory critically low?"
    - Should check `level_kg < 100`
    - Trigger low inventory alert

### 10. **Natural Language Filter Parser**
_Test: nl_filter_parser.py_

**Complex temporal queries:**
27. "Show me production from last 3 days where speed > 100"
    - Should parse: `last 3 days` + `speed > 100`
    - Combine temporal and comparison filters

28. "Power consumption between January 1 and March 31, 2024"
    - Should parse date range
    - Generate BETWEEN clause

29. "Humidity data from yesterday for zone A"
    - Should parse: `yesterday` + `zone = 'A'`
    - Combine temporal and categorical filters

30. "Actual weight greater than 50 and less than 100 from this week"
    - Should parse: `weight > 50 AND weight < 100` + `this week`
    - Complex WHERE clause generation

### 11. **Query Caching**
_Test: query_cache.py_

**Performance test:**
31. Run same query twice: "What is total production weight?"
    - First: Cache MISS, hits database
    - Second: Cache HIT, returns cached result
    - Check logs for cache performance

### 12. **RAG Integration**
_Test: rag_explorer.py_

**Questions with knowledge context:**
32. "What is OEE and how is it calculated?"
    - Should retrieve from `industrial_knowledge/` docs
    - Combine database results with RAG context

33. "Explain excess give away in manufacturing"
    - Should retrieve EGA documentation
    - Enhance explanation with domain knowledge

### 13. **End-to-End Complex Scenarios**

**Scenario A: Root Cause Analysis**
34. "Production speed dropped yesterday - find the cause"
    - Should: Check anomalies in speed
    - Should: Correlate with other metrics (weight, humidity)
    - Should: Check shift assignments
    - Should: Suggest possible root causes

**Scenario B: Performance Comparison**
35. "Compare morning shift vs night shift performance"
    - Should: Join `feedback_data` with `shift_assignments`
    - Should: Calculate metrics by shift
    - Should: Run statistical comparison
    - Should: Suggest optimization opportunities

**Scenario C: Predictive Query**
36. "When will sugar inventory run out at current usage?"
    - Should: Calculate depletion rate
    - Should: Forecast depletion date
    - Should: Alert if critical
    - Should: Suggest reorder timing

**Scenario D: Multi-Metric Dashboard**
37. "Give me a production dashboard for last week"
    - Should: Calculate multiple KPIs (EGA, speed, weight)
    - Should: Detect trends and anomalies
    - Should: Compare with targets
    - Should: Generate structured summary

### 14. **Edge Cases & Error Handling**

**Error Cases:**
38. "Show me data from table that doesn't exist"
    - Should: Graceful error handling
    - Should: Suggest available tables

39. "Calculate metric with missing data"
    - Should: Handle NULL values
    - Should: Suggest data quality checks

40. "Very complex nested query"
    - Should: Break down into simpler queries
    - Should: Use conversation memory for context

**Performance Tests:**
41. "Analyze all production data from last year"
    - Should: Use query caching
    - Should: Suggest time-bound analysis
    - Should: Use efficient aggregation

42. "Real-time monitoring query"
    - Should: Use cache for frequent queries
    - Should: Provide quick response
    - Should: Suggest alerts if thresholds breached

## 🎯 TESTING METHODOLOGY

### 1. **Manual Testing via Chat Interface**
```bash
# Start server
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Test via curl
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is average actual weight?", "session_id": "test1"}'
```

### 2. **Automated Test Script** (create test_advanced.py)
```python
import asyncio
import aiohttp
import json

async def test_query(session, query, session_id="test"):
    async with session.post('http://localhost:8000/chat', 
                          json={"query": query, "session_id": session_id}) as resp:
        return await resp.text()

async def run_tests():
    async with aiohttp.ClientSession() as session:
        tests = [
            ("What is average actual weight?", "basic_query"),
            ("Break down by variant", "follow_up"),
            ("Find anomalies in weight", "analytics"),
            # Add all test questions
        ]
        
        for query, test_name in tests:
            print(f"\n🔍 Testing: {test_name}")
            print(f"Query: {query}")
            response = await test_query(session, query)
            print(f"Response: {response[:500]}...")
```

### 3. **Monitor Logs for Feature Activation**
```bash
# Watch for specific log patterns
tail -f logs.txt | grep -E "(Vector.*selection|Cache.*HIT|Retry.*attempt|Analytics.*detected|Alert.*triggered|Suggestion.*generated)"
```

### 4. **API Endpoint Tests**
```bash
# Test alerts endpoint
curl http://localhost:8000/alerts

# Test insights endpoint
curl http://localhost:8000/insights/feedback_data/actual_weight
```

## 📊 EXPECTED OUTCOMES

### For Each Test Category:

1. **Table Selection**: Should show filtered tables with scores
2. **SQL Generation**: Should show retry attempts if needed
3. **Conversation Memory**: Should reference previous queries
4. **Analytics**: Should return statistical insights
5. **Suggestions**: Should provide 3-5 relevant follow-ups
6. **Semantic Layer**: Should use business-friendly terms
7. **Alerts**: Should trigger based on thresholds
8. **NL Parser**: Should generate correct WHERE clauses
9. **Caching**: Should show cache hits on repeated queries
10. **RAG**: Should include document context in explanations

## 🚀 QUICK START TESTING

Run these 5 critical tests first:

1. **Basic Query**: "What is average actual weight?"
2. **Follow-up**: "Break down by variant"
3. **Analytics**: "Find anomalies in weight data"
4. **Temporal**: "Show me data from last 3 days"
5. **Complex**: "Compare morning vs night shift performance"

Each should demonstrate multiple features working together.

## 📈 SUCCESS METRICS

- ✅ **Table selection accuracy**: >85% correct tables
- ✅ **SQL success rate**: >90% valid SQL
- ✅ **Response time**: <3 seconds for cached queries
- ✅ **Suggestion relevance**: >70% useful suggestions
- ✅ **Analytics detection**: Correct anomaly/trend identification
- ✅ **Memory retention**: Correct context across 3+ turns
- ✅ **Alert accuracy**: Correct threshold detection
- ✅ **Cache performance**: >50% hit rate for repeated queries

## 🔧 TROUBLESHOOTING

If features don't work:

1. **Check logs**: `tail -f logs.txt`
2. **Verify dependencies**: `pip list | grep -E "(numpy|dateparser|chromadb)"`
3. **Test database connection**: `psql -U pardhivkrishna -d iiot_feedback -c "SELECT 1;"`
4. **Check Ollama**: `curl http://localhost:11434/api/tags`
5. **Verify file paths**: All new Python files in `/production/`

## 🎉 COMPLETION CHECKLIST

- [ ] All 5 new feature files created
- [ ] App.py updated with integrations
- [ ] Requirements.txt updated
- [ ] Database connection working
- [ ] Test questions validated against schema
- [ ] Logging enabled for all features
- [ ] API endpoints accessible
- [ ] Frontend updated to show suggestions/alerts

Your chatbot is now ready for production testing with these 42 comprehensive test questions!

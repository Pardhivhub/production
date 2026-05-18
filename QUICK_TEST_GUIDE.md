# QUICK START TESTING GUIDE

## 🚀 Immediate Test Questions (Run These First)

### **5 Critical Tests to Verify All Features:**

1. **Basic + Suggestions** (Tests: Table selection, SQL generation, Suggestions)
   ```
   "What is the average actual weight?"
   ```
   ✅ Should show: SQL, results, 3-5 follow-up suggestions

2. **Follow-up + Memory** (Tests: Conversation memory, Context awareness)
   ```
   "Break it down by variant"
   ```
   ✅ Should understand "it" refers to previous query about weight

3. **Analytics + Insights** (Tests: Analytics engine, Auto insights)
   ```
   "Find anomalies in weight data"
   ```
   ✅ Should return: Statistical outliers, Z-scores, deviation percentages

4. **Temporal + NL Parsing** (Tests: NL filter parser, Complex WHERE)
   ```
   "Show me production from last 3 days where speed > 100"
   ```
   ✅ Should parse: `last 3 days` + `speed > 100` without LLM help

5. **Business Terms + Semantic** (Tests: Semantic layer, Business mapping)
   ```
   "Show me Actual Weight for Flat Cut variant"
   ```
   ✅ Should map "Actual Weight" → `actual_weight` column

## 📊 Feature-by-Feature Quick Tests

### **Table Selection** (embedder.py, table_selector.py)
```bash
# Test 1: Specific table selection
"What is the sugar inventory level?"

# Test 2: Multiple table filtering  
"Compare power cost with production weight"
```

### **SQL Self-Correction** (sql_generator.py)
```bash
# Test: Complex query that might need retry
"Calculate EGA percent where actual speed > target speed and variant is Flat Cut"
```

### **Analytics Engine** (analytics_engine.py)
```bash
# Test 1: Anomaly detection
"Find unusual power consumption"

# Test 2: Trend analysis  
"What is the trend of humidity over last week?"

# Test 3: Correlation discovery
"Do weight and speed correlate?"
```

### **Query Suggester** (query_suggester.py)
```bash
# After any query, check response JSON for:
"suggestions": [
  "Break down by variant",
  "Show me the trend over time",
  "Compare with target",
  "Find anomalies"
]
```

### **Semantic Layer** (semantic_layer.py)
```bash
# Test business term mapping
"Calculate Excess Give Away percentage"
"Show me Humidity Percent readings"
"What is the Power Consumption Cost?"
```

### **Alert System** (alert_system.py)
```bash
# Direct API test
curl http://localhost:8000/alerts

# Or ask:
"Check for any system alerts"
```

### **NL Filter Parser** (nl_filter_parser.py)
```bash
# Complex temporal queries
"Data from yesterday between 2pm and 4pm"
"Records from January 2024 where weight > 50"
"Last week's production excluding weekends"
```

### **Query Caching** (query_cache.py)
```bash
# Run same query twice
"What is total production weight?"
"What is total production weight?"  # Should be faster
```

## 🎯 Expected Output Checklist

For each test, check for:

### **Basic Query Response:**
- [ ] SQL generated and shown
- [ ] Results returned (rows, columns)
- [ ] Natural language explanation
- [ ] Suggestions (3-5 relevant follow-ups)

### **Advanced Features Indicators:**
- [ ] **Analytics**: "🔍 Automatic Insights:" section
- [ ] **Memory**: References to previous queries
- [ ] **Semantic**: Uses business-friendly column names
- [ ] **NL Parsing**: Correct WHERE clause for complex filters

### **Log Messages to Watch:**
```bash
# Start server with logging
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# In another terminal, watch logs:
tail -f logs.txt | grep -E "(SELECTED|CACHE|RETRY|ANALYTICS|SUGGEST|ALERT|SEMANTIC)"
```

## 🔧 Troubleshooting Common Issues

### **If queries fail:**
1. **Check database connection:**
   ```bash
   psql -U pardhivkrishna -d iiot_feedback -c "SELECT COUNT(*) FROM feedback_data;"
   ```

2. **Check Ollama is running:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

3. **Check dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Check logs for errors:**
   ```bash
   grep -i "error\|exception\|failed" logs.txt
   ```

### **If features don't activate:**
1. **Analytics not showing?**
   - Check `analytics_engine.py` is imported in `app.py`
   - Verify numpy is installed: `pip show numpy`

2. **Suggestions missing?**
   - Check `query_suggester.py` is imported
   - Verify schema is loaded (check startup logs)

3. **Memory not working?**
   - Check `conversation_memory.py` initialization
   - Verify session_id is being passed

## 📈 Performance Benchmarks

### **Good Performance:**
- First query: < 3 seconds
- Cached query: < 0.5 seconds  
- Analytics queries: < 5 seconds
- Memory recall: Instant

### **Acceptable Performance:**
- Complex joins: < 8 seconds
- Large result sets: < 10 seconds
- Multiple analytics: < 15 seconds

## 🧪 Automated Testing

Run the comprehensive test suite:
```bash
# Make test script executable
chmod +x test_advanced.py

# Run all tests
python test_advanced.py

# Run with custom URL
python test_advanced.py http://your-server:8000
```

## 🎉 Success Celebration Criteria

Your advanced chatbot is working if:

1. ✅ **5 Critical Tests** all pass
2. ✅ **All 5 new features** activate in logs
3. ✅ **Response times** meet benchmarks
4. ✅ **Suggestions** are relevant and useful
5. ✅ **Analytics** provide actionable insights
6. ✅ **Memory** works across 3+ turns
7. ✅ **Business terms** are correctly mapped
8. ✅ **Alerts** detect threshold breaches
9. ✅ **Caching** improves repeat query speed
10. ✅ **NL parsing** handles complex filters

## 📋 Final Verification Checklist

- [ ] Server starts without errors
- [ ] Database connection successful
- [ ] Schema loaded and enriched
- [ ] All 5 new Python files imported
- [ ] Requirements installed (numpy, dateparser)
- [ ] Test questions return expected results
- [ ] Features activate (check logs)
- [ ] API endpoints respond
- [ ] Frontend shows suggestions/alerts
- [ ] Performance meets benchmarks

## 🚀 Next Steps After Testing

1. **Enable background monitoring** (uncomment in app.py)
2. **Add custom alert rules** for your specific needs
3. **Train semantic layer** with your business glossary
4. **Configure analytics thresholds** for your KPIs
5. **Integrate with frontend** to show suggestions/alerts
6. **Set up monitoring** for query performance
7. **Add authentication** for production use
8. **Configure logging** for production debugging

## 💡 Pro Tips for Testing

1. **Use session IDs** to test memory: `session_id="test_user_1"`
2. **Check response format** includes all expected fields
3. **Verify SQL correctness** by running generated SQL manually
4. **Test edge cases**: empty results, NULL values, date boundaries
5. **Monitor resource usage** during heavy analytics queries
6. **Validate suggestions** against your actual business questions
7. **Test with real users** for feedback on suggestion relevance
8. **Measure improvement** over baseline (before advanced features)

## 🏆 Congratulations!

You now have a production-grade RAG chatbot with:
- ✅ Intelligent table selection
- ✅ Self-correcting SQL generation  
- ✅ Conversation memory
- ✅ Advanced analytics
- ✅ Proactive suggestions
- ✅ Business semantic layer
- ✅ Alert system
- ✅ NL filter parsing
- ✅ Query caching
- ✅ Comprehensive testing suite

Run the tests and watch your chatbot transform from basic Q&A to intelligent data partner!

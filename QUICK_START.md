# Quick Start Guide

## ✅ Integration Complete!

Your chatbot now:
- **Listens** to user commands like "don't join"
- **Remembers** conversation context (last 20 messages)
- **Validates** SQL queries before execution
- **Rewrites** queries that violate user constraints

## Test It Now

### 1. Start the server
```bash
cd /Users/pardhivkrishna/Desktop/production
python app.py
```

### 2. Test the conversation flow

Open your browser or use curl:

**Test 1: Normal query (no constraints)**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "How many feeders are there?"}'
```

**Test 2: Set constraint**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Don'\''t use joins, just check feedback table"}'
```

**Test 3: Check constraint is active**
```bash
curl http://localhost:8000/conversation/status
```

Expected output:
```json
{
  "message_count": 2,
  "active_constraints": {
    "no_joins": true,
    "target_table": "feedback_data"
  },
  "cached_queries": 1
}
```

**Test 4: Query with constraint applied**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Count unique feeders"}'
```

The system will:
1. Detect active constraints
2. Generate SQL with LLM
3. Validate SQL (detect if it has JOINs)
4. Rewrite if needed
5. Execute validated query

**Test 5: Clear constraints**
```bash
curl -X POST http://localhost:8000/conversation/clear
```

## What to Watch in Logs

When you run the tests, watch for these log messages:

```
✅ User constraint detected: NO JOINS
✅ User constraint detected: Target table = feedback_data
✅ Query modified by constraint validator:
   Original: SELECT COUNT(DISTINCT T1.id) FROM feedback_data AS T1 JOIN ...
   Modified: SELECT COUNT(DISTINCT feeder_id) FROM feedback_data
✅ Executing validated query
```

## Key Features

### 1. Automatic Constraint Detection
The system detects these patterns automatically:
- "don't join", "no join", "without join" → `no_joins: True`
- "feedback table", "in feedback" → `target_table: "feedback_data"`
- "count unique" → `operation: "count_distinct"`

### 2. Query Validation
Before executing any SQL:
- Checks for JOIN violations
- Checks for wrong table usage
- Rewrites query if needed
- Logs all modifications

### 3. Conversation Memory
- Stores last 20 messages
- Caches query results
- Maintains active constraints
- Provides context to LLM

## Debugging Endpoints

```bash
# Check conversation state
curl http://localhost:8000/conversation/status

# View full history
curl http://localhost:8000/conversation/history

# Clear all constraints
curl -X POST http://localhost:8000/conversation/clear
```

## Adding New Constraints

To detect new patterns, edit `conversation_manager.py`:

```python
def _extract_constraints(self, message: str):
    message_lower = message.lower()
    
    # Existing constraints...
    
    # Add your new constraint
    if "only today" in message_lower:
        self.user_constraints["time_filter"] = "today"
        logger.info("User constraint detected: TIME_FILTER = today")
```

Then handle it in `constraint_aware_query_generator.py`:

```python
def generate_query(self, user_request, schema, llm_query):
    constraints = self.conversation_manager.get_active_constraints()
    
    # Handle your new constraint
    if constraints.get("time_filter") == "today":
        llm_query = self._add_today_filter(llm_query)
    
    return llm_query
```

## Files Overview

```
production/
├── app.py                              # ✅ Integrated
├── conversation_manager.py             # ✅ New - Tracks conversation
├── constraint_aware_query_generator.py # ✅ New - Validates queries
├── INTEGRATION_COMPLETE.md             # 📖 Integration summary
├── SYSTEM_FLOW.md                      # 📖 Visual flow diagram
├── IMPROVEMENTS_README.md              # 📖 Detailed docs
└── QUICK_START.md                      # 📖 This file
```

## Troubleshooting

**Problem:** Constraints not detected
- Check logs for "User constraint detected" messages
- Verify your phrase matches patterns in `_extract_constraints()`

**Problem:** Query not rewritten
- Check if `query_generator` is initialized
- Look for "Query modified by constraint validator" in logs

**Problem:** Constraints persist too long
- Use `POST /conversation/clear` to reset
- Or restart the server

## Next Steps

1. ✅ Test the basic flow above
2. ✅ Check logs to see constraints being detected
3. ✅ Try different constraint phrases
4. ✅ Add custom constraints for your domain
5. ✅ Monitor `/conversation/status` endpoint

## Success Criteria

You'll know it's working when:
- ✅ User says "don't join" → Constraint stored
- ✅ Next query avoids JOINs even if LLM generates them
- ✅ Logs show query modifications
- ✅ `/conversation/status` shows active constraints

## Support

Check these files for more details:
- `INTEGRATION_COMPLETE.md` - What was changed
- `SYSTEM_FLOW.md` - Visual diagrams
- `IMPROVEMENTS_README.md` - Full documentation

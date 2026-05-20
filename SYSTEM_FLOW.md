# System Flow Diagram

## Before Integration (Old System)
```
User: "Don't use joins"
    ↓
LLM generates SQL with JOIN
    ↓
Execute query with JOIN ❌ (Ignores user command)
    ↓
Wrong result
```

## After Integration (New System)
```
User: "Don't use joins, check feedback table"
    ↓
ConversationManager.add_user_message()
    ↓
Extracts constraints:
  - no_joins: True
  - target_table: "feedback_data"
    ↓
Stores in memory ✅
    ↓
───────────────────────────────────────
User: "Count unique feeders"
    ↓
ConversationManager adds message
    ↓
Build context with constraints
    ↓
LLM receives:
  "ACTIVE CONSTRAINTS:
   - no_joins: True
   - target_table: feedback_data
   
   USER REQUEST: Count unique feeders"
    ↓
LLM generates: SELECT ... FROM t1 JOIN t2 ...
    ↓
ConstraintAwareQueryGenerator.generate_query()
    ↓
Detects JOIN violation ⚠️
    ↓
Rewrites to: SELECT COUNT(DISTINCT feeder_id) FROM feedback_data
    ↓
Execute modified query ✅
    ↓
Store result in cache
    ↓
Return correct answer
```

## Component Interaction

```
┌─────────────────────────────────────────────────────────┐
│                    User Message                          │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           ConversationManager                            │
│  • Stores message                                        │
│  • Extracts constraints (no_joins, target_table, etc)   │
│  • Maintains history (last 20 messages)                  │
│  • Caches query results                                  │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           Build Enhanced Context                         │
│  • Conversation history                                  │
│  • Active constraints                                    │
│  • Domain hints                                          │
│  • Schema information                                    │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           LLM (SQLGenerator)                             │
│  Receives full context and generates SQL                 │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│      ConstraintAwareQueryGenerator                       │
│  • Validates SQL against constraints                     │
│  • Detects violations (JOINs, wrong tables)              │
│  • Rewrites query if needed                              │
│  • Logs modifications                                    │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           DatabaseConnector                              │
│  Executes validated SQL                                  │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           Store Result                                   │
│  ConversationManager.add_assistant_message()             │
│  • Stores SQL                                            │
│  • Stores result                                         │
│  • Updates cache                                         │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│           Return to User                                 │
└─────────────────────────────────────────────────────────┘
```

## Constraint Detection Examples

| User Says | Detected Constraints |
|-----------|---------------------|
| "don't use joins" | `no_joins: True` |
| "check feedback table" | `target_table: "feedback_data"` |
| "count unique feeders" | `operation: "count_distinct"`, `target_column: "feeder"` |
| "without joining tables" | `no_joins: True` |
| "just in feedback" | `target_table: "feedback_data"` |
| "avoid joins" | `no_joins: True` |

## Query Rewriting Examples

### Example 1: Remove JOIN
```python
# User constraint: no_joins = True

# LLM generates:
"SELECT COUNT(DISTINCT T1.id) 
 FROM feedback_data AS T1 
 JOIN feeder_stats AS T2 ON T1.date = T2.date"

# System detects JOIN violation
# Rewrites to:
"SELECT COUNT(DISTINCT feeder_id) FROM feedback_data"
```

### Example 2: Force Specific Table
```python
# User constraint: target_table = "feedback_data"

# LLM generates:
"SELECT COUNT(*) FROM feeder_stats_line_1_jan"

# System detects wrong table
# Rewrites to:
"SELECT COUNT(DISTINCT feeder_id) FROM feedback_data"
```

## State Management

```
ConversationManager State:
├── conversation_history: [
│   ├── {role: "user", content: "don't join", timestamp: ...}
│   ├── {role: "assistant", content: "...", sql: "...", result: {...}}
│   └── ... (last 20 messages)
│   ]
├── user_constraints: {
│   ├── no_joins: True
│   ├── target_table: "feedback_data"
│   └── operation: "count_distinct"
│   }
└── query_results_cache: {
    └── "SELECT ...": {columns: [...], rows: [...]}
    }
```

## API Endpoints for Debugging

```bash
# Check current state
curl http://localhost:8000/conversation/status

# View conversation history
curl http://localhost:8000/conversation/history

# Clear all constraints (start fresh)
curl -X POST http://localhost:8000/conversation/clear
```

## Logging Output

When system is working, you'll see:
```
INFO: User constraint detected: NO JOINS
INFO: User constraint detected: Target table = feedback_data
INFO: Query modified by constraint validator:
      Original: SELECT ... FROM t1 JOIN t2 ...
      Modified: SELECT COUNT(DISTINCT feeder_id) FROM feedback_data
INFO: Executing validated query
```

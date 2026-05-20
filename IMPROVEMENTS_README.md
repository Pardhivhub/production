# Context-Aware Database Bot Improvements

## Problems Solved

### 1. **Bot Not Listening to User Commands**
- **Problem**: Bot ignores constraints like "don't use joins"
- **Solution**: `ConversationManager` extracts and stores user constraints from messages
- **Implementation**: Constraint detection in `_extract_constraints()` method

### 2. **No Conversation Context/Cache**
- **Problem**: Bot doesn't remember previous messages or query results
- **Solution**: Full conversation history with query results cached
- **Implementation**: `conversation_history` and `query_results_cache` in `ConversationManager`

### 3. **Repeated Mistakes**
- **Problem**: Bot makes same mistakes even after correction
- **Solution**: `ConstraintAwareQueryGenerator` validates and rewrites queries
- **Implementation**: Query validation before execution

## Key Components

### 1. ConversationManager (`conversation_manager.py`)
Tracks conversation state and user constraints:

```python
# Automatically detects constraints from user messages
conversation_manager.add_user_message("don't use joins, check feedback table")

# Stores constraints:
# - no_joins: True
# - target_table: feedback_data
# - operation: count_distinct
```

**Features:**
- Extracts constraints from natural language
- Maintains conversation history (last 20 messages)
- Caches query results
- Provides context for LLM prompts

### 2. ConstraintAwareQueryGenerator (`constraint_aware_query_generator.py`)
Validates and modifies LLM-generated queries:

```python
# LLM generates: SELECT ... FROM t1 JOIN t2 ...
# User said: "don't use joins"
# Generator rewrites: SELECT COUNT(DISTINCT feeder_id) FROM feedback_data
```

**Features:**
- Detects JOIN violations
- Rewrites queries to respect constraints
- Builds context-aware prompts for LLM
- Logs all modifications

### 3. ContextAwareDatabaseBot (`context_aware_bot_example.py`)
Integrates everything together:

```python
bot = ContextAwareDatabaseBot(db_url)
await bot.initialize()

# Process messages with full context
response = await bot.process_user_message(
    "count unique feeders in feedback",
    llm_generated_query=llm_query  # Will be validated/modified
)
```

## How It Works

### Flow Diagram
```
User Message
    ↓
ConversationManager.add_user_message()
    ↓ (extracts constraints)
Active Constraints: {no_joins: True, target_table: "feedback_data"}
    ↓
LLM generates query (with context prompt)
    ↓
ConstraintAwareQueryGenerator.generate_query()
    ↓ (validates against constraints)
Modified Query (if needed)
    ↓
DatabaseConnector.execute_query()
    ↓
ConversationManager.add_assistant_message()
    ↓ (stores result in cache)
Response to User
```

## Integration Steps

### Step 1: Add to Your Existing System

```python
from conversation_manager import ConversationManager
from constraint_aware_query_generator import ConstraintAwareQueryGenerator

# Initialize
conversation_manager = ConversationManager()
query_generator = ConstraintAwareQueryGenerator(conversation_manager)
```

### Step 2: Wrap Your LLM Query Generation

```python
# Before (current system)
llm_query = llm.generate_sql(user_message)
result = await db.execute_query(llm_query)

# After (with improvements)
conversation_manager.add_user_message(user_message)

# Build context-aware prompt
context_prompt = query_generator.build_context_prompt(user_message, schema)
llm_query = llm.generate_sql(context_prompt)  # LLM gets full context

# Validate and modify query based on constraints
final_query = query_generator.generate_query(user_message, schema, llm_query)

# Execute
result = await db.execute_query(final_query)

# Store result
conversation_manager.add_assistant_message(
    response_text,
    sql_query=final_query,
    query_result=result
)
```

### Step 3: Use Context in LLM Prompts

```python
# Get conversation context for LLM
context = conversation_manager.get_conversation_context(last_n=5)

# Build enhanced prompt
prompt = f"""
{context}

ACTIVE CONSTRAINTS:
{conversation_manager.get_active_constraints()}

USER REQUEST: {user_message}

Generate SQL query respecting all constraints above.
"""
```

## Constraint Detection Examples

The system automatically detects these patterns:

| User Says | Detected Constraint |
|-----------|-------------------|
| "don't use joins" | `no_joins: True` |
| "check feedback table" | `target_table: "feedback_data"` |
| "count unique feeders" | `operation: "count_distinct"`, `target_column: "feeder"` |
| "without joining" | `no_joins: True` |
| "just in feedback" | `target_table: "feedback_data"` |

## Query Rewriting Examples

### Example 1: Remove Joins
```python
# LLM generates:
"SELECT COUNT(DISTINCT T1.id) FROM feedback_data AS T1 JOIN feeder_stats AS T2 ON T1.date = T2.date"

# User constraint: no_joins = True
# System rewrites to:
"SELECT COUNT(DISTINCT feeder_id) FROM feedback_data"
```

### Example 2: Use Specific Table
```python
# LLM generates:
"SELECT COUNT(*) FROM feeder_stats_line_1_jan"

# User constraint: target_table = "feedback_data"
# System rewrites to:
"SELECT COUNT(DISTINCT feeder_id) FROM feedback_data"
```

## Benefits

1. **Persistent Memory**: Bot remembers last 20 messages and all constraints
2. **Constraint Enforcement**: Automatically validates queries before execution
3. **Context-Aware**: LLM receives full conversation context in prompts
4. **Query Cache**: Avoids re-executing identical queries
5. **Debugging**: All modifications logged for troubleshooting
6. **Flexible**: Easy to add new constraint types

## Adding New Constraints

To detect new constraint types, add to `_extract_constraints()`:

```python
def _extract_constraints(self, message: str):
    message_lower = message.lower()
    
    # Existing constraints...
    
    # Add new constraint
    if "only recent" in message_lower or "last week" in message_lower:
        self.user_constraints["time_filter"] = "recent"
        logger.info("User constraint detected: TIME_FILTER = recent")
```

Then handle it in `ConstraintAwareQueryGenerator`:

```python
def generate_query(self, user_request, schema, llm_query):
    constraints = self.conversation_manager.get_active_constraints()
    
    # Handle new constraint
    if constraints.get("time_filter") == "recent":
        llm_query = self._add_time_filter(llm_query)
    
    return llm_query
```

## Testing

Run the example:

```bash
python context_aware_bot_example.py
```

Expected output shows:
- Constraints being detected
- Queries being rewritten
- Context being maintained across messages

## Next Steps

1. **Integrate with your LLM**: Pass `context_prompt` to your LLM
2. **Add more constraints**: Extend `_extract_constraints()` for your use cases
3. **Persist conversations**: Save conversation history to database
4. **Add feedback loop**: Let users confirm/reject query modifications

## Configuration

```python
# Adjust history size
conversation_manager = ConversationManager(max_history=50)

# Clear constraints when starting new topic
conversation_manager.clear_all_constraints()

# Check current state
summary = conversation_manager.get_summary()
print(summary)
```

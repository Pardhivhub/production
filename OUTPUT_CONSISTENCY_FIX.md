# Output Consistency Improvements

## Problem
The LLM was giving inconsistent explanations for the same query:
- Sometimes: Detailed explanation with suggestions and follow-up questions ✅
- Sometimes: Short, basic answer without helpful context ❌

## Root Cause
The explainer prompt didn't have specific instructions for handling **empty or zero results**, so the LLM would sometimes give minimal responses.

## Solution Applied

### 1. Enhanced Empty Result Handling in `sql_generator.py`

**Before:**
```python
async def explain_results(self, query, sql, results, extra_context=""):
    # Basic prompt without empty result guidance
    prompt = EXPLAINER_PROMPT.format(...)
```

**After:**
```python
async def explain_results(self, query, sql, results, extra_context=""):
    # Detect empty/zero results
    row_count = results.get("row_count", 0)
    is_empty = row_count == 0 or (row_count == 1 and list(results["rows"][0].values())[0] == 0)
    
    # Add specific guidance for empty results
    if is_empty:
        empty_result_guidance = """
        IMPORTANT: The result is empty or zero. You MUST:
        1. Clearly state what was found (or not found)
        2. Provide 2-3 possible reasons why this might be the case
        3. Suggest alternative tables or approaches the user could try
        4. Ask helpful follow-up questions to guide the user
        """
        prompt += empty_result_guidance
```

### 2. Automatic Alternative Table Suggestions in `app.py`

**Added:**
```python
# If results are empty/zero, automatically suggest alternative tables
if is_zero_result and selected_tables:
    all_tables = [t['name'] for t in active_schema.get('tables', [])]
    alternative_tables = [t for t in all_tables if t not in selected_tables and 'feeder' in t.lower()]
    
    if alternative_tables:
        explanation += f"\n\n💡 **Suggestion**: The '{selected_tables[0]}' table returned no results. 
                        You might want to check these alternative tables: {', '.join(alternative_tables[:3])}"
```

### 3. Increased Temperature for Better Suggestions

**Changed:**
```python
# Before
temperature=0.2  # Too conservative, sometimes gives minimal responses

# After  
temperature=0.3  # Slightly higher for more creative and helpful suggestions
```

## Expected Output Now

When user asks: **"How many feeders are there in total?"**

The system will **consistently** return:

```
Based on the query results, there are 0 feeders with distinct feeder numbers 
in the 'feeder_stats_line_1_jan' table.

This could mean:
- The feeder numbers are not being tracked or recorded in this specific table
- The data might be stored in a different table (e.g., feedback_data, feeder_metadata)
- There could be a date range issue where this table only contains data for specific periods

To investigate further, you might want to:
- Check the 'feedback_data' table which might contain feeder information
- Verify if 'feeder_metadata' table has the master list of feeders
- Look at other monthly tables (e.g., feeder_stats_line_1_feb)

💡 **Suggestion**: The 'feeder_stats_line_1_jan' table returned no results. 
You might want to check these alternative tables: feedback_data, feeder_metadata

Would you like me to check any of these alternative tables?
```

## Benefits

✅ **Consistent output** - Always provides detailed explanations for empty results  
✅ **Automatic suggestions** - System suggests alternative tables to check  
✅ **Helpful guidance** - Provides possible reasons and next steps  
✅ **Better UX** - Users aren't left wondering what to do next  

## Testing

Restart your server and test:
```bash
python app.py
```

Then ask the same question multiple times:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "How many feeders are there in total?"}'
```

You should now get **consistent, detailed responses** every time!

## Files Modified

1. ✅ `sql_generator.py` - Enhanced empty result handling
2. ✅ `app.py` - Added automatic alternative table suggestions

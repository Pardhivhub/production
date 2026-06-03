# 📊 Database Data Guide

## Actual Data in Your Database

Based on the schema inspection, here's what data actually exists:

### EGA Details Data (`ega_details_data`)

**Available Grammage Values:**
- `100g`
- `200g`
- `250g`

**Note:** There is NO `10.5g` in the database

**Available Variants:**
- `Flat Cut`
- `Ridge Cut`

**Available Machines:**
- Machine IDs: M01, M02, M03, etc.

**Available Dates:**
- Sample data: 2026-05-20 (future date)
- Your query used: 2025-05-29 (may not exist)

---

## ✅ Correct Query Examples

### Example 1: Highest EGA (Using Actual Data)

**Your Original Query:**
```
which machine had the highest EGA percent on 2025-05-29 for the 10.5g Ridge Cut variant?
```

**Issue:** 
- No `10.5g` in database (only 100g, 200g, 250g)
- No data for 2025-05-29 (sample data is from 2026)

**Fixed Query (Using Actual Data):**
```
which machine had the highest EGA percent on 2026-05-20 for the 100g Ridge Cut variant?
```

**Generated SQL:**
```sql
SELECT machine_id FROM ega_details_data 
WHERE start_time::date = '2026-05-20' 
AND grammage = '100g' 
AND variant = 'Ridge Cut' 
ORDER BY ega_percent DESC 
LIMIT 1
```

---

### Example 2: Check Available Data

**Query:**
```
What data is available in ega_details_data?
```

**What it will show:**
- All distinct combinations of grammage, variant, date
- Sample rows from the table

**Generated SQL:**
```sql
SELECT DISTINCT 
  grammage, 
  variant, 
  DATE(start_time) as date,
  COUNT(*) as count
FROM ega_details_data 
GROUP BY grammage, variant, DATE(start_time)
ORDER BY DATE DESC
```

---

### Example 3: EGA for Specific Date & Variant

**Query:**
```
Show me highest EGA for 100g Flat Cut on 2026-05-20
```

**Generated SQL:**
```sql
SELECT machine_id, ega_percent, start_time FROM ega_details_data 
WHERE start_time::date = '2026-05-20' 
AND grammage = '100g' 
AND variant = 'Flat Cut' 
ORDER BY ega_percent DESC 
LIMIT 1
```

---

## 🔍 To Find Available Data

### Check Grammage Values
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "
SELECT DISTINCT grammage 
FROM ega_details_data 
ORDER BY grammage;"
```

**Output:**
```
grammage
---------
100g
200g
250g
```

### Check Variants
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "
SELECT DISTINCT variant 
FROM ega_details_data 
ORDER BY variant;"
```

**Output:**
```
variant
-----------
Flat Cut
Ridge Cut
```

### Check Date Range
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "
SELECT MIN(DATE(start_time)) as earliest, 
       MAX(DATE(start_time)) as latest,
       COUNT(*) as total_rows
FROM ega_details_data;"
```

**Output (Example):**
```
earliest   | latest     | total_rows
-----------+------------+-----------
2026-05-20 | 2026-05-20 | 6
```

### Check Available Machines
```bash
psql -h localhost -p 5432 -U pardhivkrishna -d iiot_feedback -c "
SELECT DISTINCT machine_id 
FROM ega_details_data 
ORDER BY machine_id;"
```

---

## 📝 Schema Reference

### `ega_details_data` Columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | Primary key |
| `machine_id` | text | Machine identifier (e.g., M01) |
| `loop_id` | text | Production loop |
| `grammage` | text | Weight in grams with 'g' suffix (e.g., '100g') |
| `variant` | text | Product variant (Flat Cut, Ridge Cut) |
| `start_time` | timestamp | Measurement time |
| `actual_weight` | double | Actual measured weight |
| `target_weight` | double | Target weight |
| `ega_percent` | double | EGA percentage value |
| `created_at` | timestamp | Record creation time |

### Other Tables

**`oee_details_data`**
- Columns: machine_id, loop_id, grammage, variant, oee, availability, performance, quality, timestamp
- Time column: `timestamp`

**`wastage_records`**
- Columns: machine_id, line_id, wastage_kg, reason, shift, operator_name, timestamp
- Time column: `timestamp`

**`production_speed_details_data`**
- Columns: machine_id, loop_id, variant, grammage, production_speed, start_time
- Time column: `start_time`

---

## 🎯 Common Query Patterns

### Pattern 1: Highest Metric
```
Which machine had the highest [metric] for [variant] on [date]?
```
**Example:** "Which machine had the highest EGA percent for Ridge Cut on 2026-05-20?"

### Pattern 2: Filter by Threshold
```
Show machines with [metric] above [value] for [variant]
```
**Example:** "Show machines with EGA above 2.5 for 100g Ridge Cut"

### Pattern 3: Compare Variants
```
Compare [metric] between [variant1] and [variant2]
```
**Example:** "Compare EGA between Flat Cut and Ridge Cut on 2026-05-20"

### Pattern 4: Time Range
```
Show [metric] trends for [variant] from [start_date] to [end_date]
```
**Example:** "Show EGA trends for 100g Flat Cut from 2026-05-20 to 2026-05-21"

---

## 🚀 Using the Chatbot Correctly

### Step 1: Start the App
```bash
./START_APP.sh
```

### Step 2: First, Check Available Data
```
Show me what data is available for EGA
```

### Step 3: Use Actual Values from Results
Once you see what grammage/variant/date combinations exist, use those in your queries.

### Step 4: Ask Your Question
```
Which machine had the highest EGA percent for 100g Ridge Cut on 2026-05-20?
```

---

## 🔧 Debugging Your Query

Use the debug script to see exactly what's happening:

```bash
python3 debug_chatbot.py "which machine had the highest EGA percent on 2026-05-20 for the 100g Ridge Cut variant?"
```

**Output shows:**
1. KPI engine analysis
2. Table selection
3. Generated SQL
4. Query execution
5. Results

---

## ✅ Query Fix Summary

| Issue | Old | New |
|-------|-----|-----|
| Grammage format | `10.5` | `'100g'` |
| Column name | `machine_name` | `machine_id` |
| Date | `2025-05-29` | `2026-05-20` (actual data) |
| Quotes | No quotes | Single quotes for text |
| Query structure | No ORDER BY | `ORDER BY ega_percent DESC LIMIT 1` |

---

## 📞 Need Help?

1. **Check available data** in your database
2. **Use debug script** to see what SQL is generated
3. **Refer to STARTUP_GUIDE.md** for troubleshooting
4. **Check CHATBOT_IMPROVEMENTS_SUMMARY.md** for technical details

Now you're ready to use the chatbot correctly! 🎉

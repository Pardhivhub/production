# GLOBAL RULES: Cross-cutting rules for all tables
# VERIFIED AGAINST LIVE DATABASE SCHEMA — DO NOT OVERRIDE

## 1. POSTGRES SYNTAX & NULL SAFETY
- **Case Insensitive Matching**: Always use `ILIKE` instead of `=` for string attributes (e.g. `variant ILIKE '%Ridge Cut%'`).
- **Grouping by Time**: Use `DATE_TRUNC('hour', start_time)`, `DATE_TRUNC('day', start_time)`, etc.
- **Division Safety**: ALWAYS wrap division denominators in `NULLIF` (e.g. `a / NULLIF(b, 0)`).
- **COALESCE**: Use `COALESCE(value, 0)` on nullable numeric columns before arithmetic.

## 2. MACHINE NAME — CRITICAL RULE (NO JOIN REQUIRED)
- `ega_details_data`, `oee_details_data`, and `production_speed_details_data` ALL have a `machine_name` column DIRECTLY in the table.
- ✗ NEVER JOIN these tables to the `machines` table just to get `machine_name`. It already exists.
- ✓ Simply use `machine_name` directly: `GROUP BY machine_id, machine_name`

## 3. TIME COLUMNS (PER TABLE)
- `ega_details_data`: use `start_time`
- `oee_details_data`: use `start_time`
- `production_speed_details_data`: use `start_time`
- `wastage_records`: use `production_start_time` — NEVER use `start_time`
- `gsm_usage_details`: use `date` — NEVER use `start_time`
- **Today**: `start_time >= CURRENT_DATE AND start_time < CURRENT_DATE + INTERVAL '1 day'`
- **Yesterday**: `start_time >= CURRENT_DATE - INTERVAL '1 day' AND start_time < CURRENT_DATE`
- **This Week**: `start_time >= DATE_TRUNC('week', CURRENT_DATE)`
- **Last Month**: `start_time >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') AND start_time < DATE_TRUNC('month', CURRENT_DATE)`

## 4. SHIFT MAPPING
- `wastage_records` has a `shift` column with values 'A', 'B', 'C' — use `shift = 'A'` directly.
- `ega_details_data` and `oee_details_data` do NOT have a `shift` column. Use HOUR extraction from `start_time`:
  - **Morning (Shift A)**: `EXTRACT(HOUR FROM start_time) >= 6 AND EXTRACT(HOUR FROM start_time) < 14`
  - **Afternoon (Shift B)**: `EXTRACT(HOUR FROM start_time) >= 14 AND EXTRACT(HOUR FROM start_time) < 22`
  - **Night (Shift C)**: `(EXTRACT(HOUR FROM start_time) >= 22 OR EXTRACT(HOUR FROM start_time) < 6)`

## 5. GRAMMAGE COLUMN
- `ega_details_data`: `grammage` is NUMERIC — compare numerically: `grammage = 10.5`
- `oee_details_data`: `grammage` is NUMERIC — compare numerically: `grammage = 100`
- `wastage_records`: `grammage` is NUMERIC — compare numerically
- `production_speed_details_data`: `grammage` is NUMERIC
- ✗ NEVER filter grammage with a 'g' suffix (e.g. `grammage = '100g'` is WRONG). Strip any 'g' suffix.

## 6. SORTING AND RANKING
- "Highest", "most", "top N" → `ORDER BY metric DESC LIMIT N`
- "Lowest", "least", "worst" (for OEE/EGA), "bottom N" → `ORDER BY metric ASC LIMIT N`
- **Availability Inversion**: "Best availability" = lowest downtime (`ORDER BY SUM(downtime_mins) ASC`).

## 7. ALIAS NAMING
- Always alias metric columns clearly (e.g., `AS ega_percent`, `AS oee_percent`, `AS total_downtime_mins`, `AS wastage_kg`).

## 8. "ALL" OR "EACH" QUERIES
- ✗ NEVER add `WHERE machine_id = N` if the user asks for all machines, each machine, or grouped by machine.
- ✓ Use `GROUP BY machine_id, machine_name` for per-machine queries.

## 9. COMPARE QUERIES (MULTI-MACHINE)
- If user asks to "compare machine 4 and machine 7":
  1. Add `WHERE machine_id IN (4, 7)`
  2. Add `GROUP BY machine_id, machine_name`
  3. Add `ORDER BY machine_id`

## 10. JOINS — WHEN TO JOIN
- Join `machines` only when you need extra columns from `machines` (e.g., `machine_name` not in the facts table — but for OEE/EGA/speed it IS already there).
- Join `gmiiot_plants` on `wastage_records.plant_id = gmiiot_plants.plant_id` for plant name.
- Join `gmiiot_lines` on `wastage_records.line_id = gmiiot_lines.id` for line name. (`gmiiot_lines` PK is `id`, column is `line_name`).
- `machines` PK is `id`. Join: `JOIN machines m ON t.machine_id = m.id`
- ✓ `variant` and `grammage` are ALREADY columns directly in `ega_details_data`, `oee_details_data`, `production_speed_details_data`, and `wastage_records`.
- ✗ NEVER join any other table (like `gsm_usage_details` or `variant` or `ega_details_data`) to get `variant` or `grammage` for OEE/speed queries. Use them directly from the main table.

## 11. NESTED AGGREGATES & COMPLEX MATH
- 🚨 CRITICAL: PostgreSQL FORBIDS nested aggregates like `AVG(SUM(good_bags))`, `MAX(SUM(t_weight))`, or `MIN(((SUM(a)-SUM(b))/SUM(c)))`.
- If a question asks for the "Highest", "Lowest", or "Average" of a calculated metric (like OEE or EGA):
  - Do NOT nest `MAX()` or `AVG()` around the formula.
  - Instead, use a **Subquery** or **CTE** to calculate the grouped formula first, then query `MAX()`, `MIN()`, or `AVG()` from that subquery.

## 12. ALIASING & COLUMNS
- 🚨 CRITICAL: NEVER use `m.machine_id` unless you explicitly wrote `JOIN machines m`. If `machine_id` is on the fact table, just use `machine_id`.
- 🚨 CRITICAL: `availability` is NOT a real column. If a question asks for availability, you MUST compute it: `(SUM(run_duration)/NULLIF(SUM(run_duration + downtime_mins), 0)) * 100 AS availability_percent`

## WORKED EXAMPLES

Q: Compare EGA percent between machine 7 and machine 8
SQL: SELECT machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) * 100 AS ega_percent FROM ega_details_data WHERE machine_id IN (7, 8) GROUP BY machine_id, machine_name ORDER BY machine_id

Q: Show EGA percent grouped by machine
SQL: SELECT machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) * 100 AS ega_percent FROM ega_details_data GROUP BY machine_id, machine_name ORDER BY machine_name

Q: OEE for each machine today
SQL: SELECT machine_name, (((SUM(good_bags)/NULLIF(SUM(1)*60-SUM(downtime_mins),0))/NULLIF(AVG(target_speed),0)*100) * ((SUM(1)*60-SUM(downtime_mins))/NULLIF(SUM(1)*60,0)*100) * (CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100-((SUM(overlimit_count)+SUM(failed_bags))/NULLIF(SUM(good_bags),0))*100 END)) / 10000 AS oee_percent FROM oee_details_data WHERE start_time >= CURRENT_DATE AND start_time < CURRENT_DATE + INTERVAL '1 day' GROUP BY machine_id, machine_name ORDER BY oee_percent DESC

Q: Average production speed by variant and grammage
SQL: SELECT variant, grammage, AVG(speed.value::numeric) AS avg_speed_bpm FROM production_speed_details_data psd CROSS JOIN LATERAL jsonb_array_elements_text(psd.production_speed_bpm) AS speed(value) GROUP BY variant, grammage ORDER BY avg_speed_bpm DESC

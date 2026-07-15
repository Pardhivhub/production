# TABLE: ega_details_data

# VERIFIED AGAINST LIVE DATABASE SCHEMA

## PURPOSE

Stores machine-wise hourly production and EGA (Extra Giveaway Amount) metrics.
Tracks packaging weights, actual vs theoretical pack weights, and target limits to measure material giveaway loss.
Data is captured every one hour per machine.

## COLUMNS (COMPLETE LIST — VERIFIED)

- `machine_id`: Integer ID of the machine.
- `machine_name`: TEXT — machine name (e.g. 'Machine-1'). USE DIRECTLY, no JOIN needed.
- `loop_id`: Integer ID of the production loop/line.
- `loop_name`: TEXT — name of the production line. USE DIRECTLY, no JOIN needed.
- `plant_unit`: TEXT — plant unit identifier.
- `preset_no`: INTEGER — preset number configured on the machine.
- `grammage`: NUMERIC — SKU weight in grams (e.g. 10.5, 100). Compare NUMERICALLY, never with 'g' suffix.
- `variant`: TEXT — product variant (e.g. 'Ridge Cut', 'Flat Cut'). Use ILIKE for matching.
- `start_time`: TIMESTAMP — start of the hourly record. USE FOR ALL DATE FILTERING.
- `end_time`: TIMESTAMP — end of the hourly record.
- `t_weight`: DOUBLE PRECISION — total actual packed weight in grams. (Summable)
- `theoretical_pack_weight`: DOUBLE PRECISION — total theoretical target weight in grams. (Summable)
- `mean_weight`: NUMERIC — average weight of checked packs.
- `ega_percent`: NUMERIC — pre-calculated EGA % for the specific hour only (DO NOT AVG this).
- `ega_gm`: DOUBLE PRECISION — pre-calculated EGA loss in grams for the specific hour only.
- `ega_limit`: NUMERIC — EGA limit threshold.
- `proper`: BIGINT — number of properly weighed bags.
- `over_scale`: INTEGER — number of over-scale bags.
- `over_weight`: INTEGER — number of over-weight bags.
- `total_weight_od`: DOUBLE PRECISION — total weight over deviation.
- `total_dumps`: BIGINT — total number of dumps.
- `run_duration`: NUMERIC — actual running duration in minutes.
- `average_speed`: NUMERIC — average speed in bags/min.
- `target_speed`: INTEGER — target speed in bags/min.
- `total_weight`: DOUBLE PRECISION — total weight processed.

## FORMULAS

EGA calculations for multiple hours/days MUST be computed dynamically using SUM:

- **EGA Giveaway %** = `((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0)) * 100`

## JOIN RULES

- ✓ `machine_name` is ALREADY in the table — NO JOIN to `machines` is needed.
- ✓ `loop_name` is ALREADY in the table — NO JOIN to `gmiiot_lines` is needed.
- Only JOIN `machines` if you need extra columns from machines not already here.

## FORBIDDEN PATTERNS

- ✗ NEVER use `AVG(ega_percent)`. For any aggregation, use the SUM formula above.
- ✗ NEVER join `ega_details_data` to `wastage_records` directly.
- ✗ NEVER add a `plant_id` column — it does NOT exist in this table.
- ✗ NEVER filter grammage with a 'g' suffix — grammage is NUMERIC (e.g. use `grammage = 10.5` not `grammage = '10.5g'`).
- ✗ NEVER JOIN machines just to get machine_name — it's already in the table.

## ROOT CAUSE ANALYSIS ("WHY" QUERIES)

- If user asks "Why is EGA high?" or "reasons for EGA loss", query driver columns alongside EGA:
  `SUM(over_scale)`, `SUM(over_weight)`, `SUM(total_dumps)`, `AVG(mean_weight)`, `ega_limit`

## WORKED EXAMPLES

Q: What is the total EGA percentage across all machines?
SQL: SELECT ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data

Q: Show EGA percent grouped by machine
SQL: SELECT machine_id, machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data GROUP BY machine_id, machine_name ORDER BY ega_percent DESC

Q: Show me the EGA for machine 14 yesterday
SQL: SELECT machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data WHERE machine_id = 14 AND start_time >= CURRENT_DATE - INTERVAL '1 day' AND start_time < CURRENT_DATE GROUP BY machine_id, machine_name

Q: Which machine has the lowest EGA percentage this month?
SQL: SELECT machine_id, machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data WHERE start_time >= DATE_TRUNC('month', CURRENT_DATE) GROUP BY machine_id, machine_name ORDER BY ega_percent ASC LIMIT 1

Q: Show EGA percent by day for the past 30 days
SQL: SELECT DATE_TRUNC('day', start_time) AS day, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data WHERE start_time >= CURRENT_DATE - INTERVAL '30 days' GROUP BY DATE_TRUNC('day', start_time) ORDER BY day ASC

Q: EGA for ridge cut variant
SQL: SELECT variant, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent FROM ega_details_data WHERE variant ILIKE '%ridge cut%' GROUP BY variant

Q: Why was EGA high last month? (Root cause breakdown by machine)
SQL: SELECT machine_id, machine_name, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) \* 100 AS ega_percent, SUM(over_scale) AS total_over_scale, SUM(over_weight) AS total_over_weight, SUM(total_dumps) AS total_dumps, AVG(mean_weight) AS avg_mean_weight FROM ega_details_data WHERE start_time >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') AND start_time < DATE_TRUNC('month', CURRENT_DATE) GROUP BY machine_id, machine_name ORDER BY ega_percent DESC

Q: Show over-scale bags count by machine
SQL: SELECT machine_id, machine_name, SUM(over_scale) AS total_over_scale FROM ega_details_data GROUP BY machine_id, machine_name ORDER BY total_over_scale DESC

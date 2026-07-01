# TABLE: ega_details_data

## PURPOSE
Stores machine-wise hourly production and EGA (Extra Giveaway Amount) metrics. Tracks packaging weights, actual vs theoretical pack weights, and target limits to measure material giveaway loss. Data is captured every one hour per machine.

## COLUMNS (COMPLETE LIST)
- `t_weight`: Total actual packed weight in grams. (Summable)
- `theoretical_pack_weight`: Total theoretical target weight in grams. (Summable)
- `mean_weight`: Arithmetic average weight of checked packs.
- `ega_percent`: Pre-calculated EGA percentage for the specific hour.
- `ega_gm`: Pre-calculated EGA loss in grams for the specific hour.
- `proper`: Number of properly weighed bags.
- `over_scale`: Number of over-scale bags.
- `over_weight`: Number of over-weight bags.
- `total_weight_od`: Total weight over deviation.
- `total_dumps`: Total number of dumps.
- `machine_id`: Foreign key to machines table.
- `loop_id`: ID of the production line.
- `start_time`: The timestamp of the record. USE THIS FOR ALL DATE FILTERING.
- `end_time`: The end timestamp of the record hour.
- `grammage`: SKU weight category (e.g., '100g', '10.5g').
- `variant`: Product variant type (e.g., 'Ridge Cut', 'Flat Cut').

## FORMULAS
EGA calculations for multiple hours/days must be computed dynamically.
- **EGA Giveaway %** = `((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0)) * 100`

## JOIN RULES
- To join with machines: `ega_details_data JOIN machines ON ega_details_data.machine_id = machines.machine_id` (NEVER join on `id` or `machine_name`)
- To join with lines: `ega_details_data JOIN gmiiot_lines ON ega_details_data.loop_id = gmiiot_lines.loop_id`

## FORBIDDEN PATTERNS
- ✗ NEVER use `AVG(ega_percent)`. You MUST recalculate using the formula above when aggregating.
- ✗ NEVER join `ega_details_data` to `wastage_records` directly.
- ✗ NEVER invent a `plant_id` column.

## FILTERING & OUTLIERS
- Date filtering MUST use `start_time` (e.g., `start_time BETWEEN '2026-06-01' AND '2026-06-30 23:59:59'`).

## WORKED EXAMPLES

Q: What is the total EGA percentage?
SQL: SELECT ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) * 100 AS ega_percent FROM ega_details_data

Q: Show me the EGA for machine 14 yesterday
SQL: SELECT m.machine_name, ((SUM(e.t_weight) - SUM(e.theoretical_pack_weight)) / NULLIF(SUM(e.t_weight),0)) * 100 AS ega_percent FROM ega_details_data e JOIN machines m ON e.machine_id = m.machine_id WHERE e.machine_id = 14 AND e.start_time BETWEEN '2026-06-30' AND '2026-06-30 23:59:59' GROUP BY m.machine_name

Q: Show EGA percent by day for the past 30 days
SQL: SELECT DATE_TRUNC('day', start_time) AS day, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) * 100 AS ega_percent FROM ega_details_data WHERE start_time >= CURRENT_DATE - INTERVAL '30 days' GROUP BY DATE_TRUNC('day', start_time) ORDER BY day ASC

Q: What is the EGA for ridge cut variant?
SQL: SELECT variant, ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight),0)) * 100 AS ega_percent FROM ega_details_data WHERE variant ILIKE '%ridge cut%' GROUP BY variant

Q: Show over-scale bags count by machine
SQL: SELECT m.machine_name, SUM(e.over_scale) AS total_over_scale FROM ega_details_data e JOIN machines m ON e.machine_id = m.machine_id GROUP BY m.machine_name

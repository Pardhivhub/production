# TABLE: wastage_records

## PURPOSE
Stores shift-wise wastage and production rejection data entered manually by operators, JTAs, or shift in-charges. Captures total wastage quantity, wastage reasons, production rejection, and unaccounted downtime details.

## COLUMNS (COMPLETE LIST)
- `wastage_kg`: Weight of wasted packaging material in kg. (Summable)
- `filled_bag_rejection`: Quantitative rejections in kilograms. (Summable)
- `failed_bag_rejection`: Quantitative rejections in kilograms. (Summable)
- `manual_rejection_kg`: Operator manual rejection in kg. (Summable)
- `plant_id`: ID of the plant.
- `line_id`: ID of the line.
- `machine_id`: ID of the machine.
- `shift`: Operational shift name (e.g., 'A', 'B', 'C'). MUST BE EXACT MATCH (uppercase).
- `flavour`: Product flavour name (e.g., 'Salted', 'Ridge Cut'). Note: Wastage records do NOT have a `variant` column, they use `flavour` instead.
- `grammage`: Product grammage SKU (e.g., '100g', '10.5g'). MUST HAVE 'g' SUFFIX.
- `production_start_time`: The start timestamp of the shift. USE THIS FOR ALL DATE FILTERING.
- `production_end_time`: The end timestamp of the shift.
- `operator_name`: Name of the operator.
- `jta_name`: Name of the JTA.
- `shift_incharge_name`: Name of the shift incharge.
- `wastage_breakdown`: TEXT column containing JSON-encoded categorizations.
- `unaccounted_downtime_breakdown`: TEXT column containing JSON-encoded downtime categories.

## FORMULAS
- **JSON Extract**: To extract keys from the breakdown columns, cast to jsonb: `CAST(wastage_breakdown AS jsonb)->>'key'`

## JOIN RULES
- To join with plants: `wastage_records JOIN gmiiot_plants ON wastage_records.plant_id = gmiiot_plants.plant_id`
- To join with lines: `wastage_records JOIN gmiiot_lines ON wastage_records.line_id = gmiiot_lines.loop_id`
- To join with machines: `wastage_records JOIN machines ON wastage_records.machine_id = machines.machine_id`

## FORBIDDEN PATTERNS
- ✗ NEVER use `start_time` for date filtering. You MUST use `production_start_time`.
- ✗ NEVER use the `variant` column. You MUST use `flavour`.

## FILTERING & OUTLIERS
- Date filtering MUST use `production_start_time` (e.g., `production_start_time BETWEEN '2026-06-01' AND '2026-06-30 23:59:59'`).

## WORKED EXAMPLES

Q: Total wastage by plant name
SQL: SELECT p.plant_name, SUM(w.wastage_kg) AS total_wastage_kg FROM wastage_records w JOIN gmiiot_plants p ON w.plant_id = p.plant_id GROUP BY p.plant_name

Q: List all wastage entries for machine 7 on June 28
SQL: SELECT * FROM wastage_records w JOIN machines m ON w.machine_id = m.machine_id WHERE m.machine_id = 7 AND w.production_start_time BETWEEN '2026-06-28' AND '2026-06-28 23:59:59'

Q: Total wastage comparison: this month vs last month
SQL: SELECT EXTRACT(MONTH FROM production_start_time) as month, SUM(wastage_kg) AS total_wastage FROM wastage_records WHERE production_start_time >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') GROUP BY EXTRACT(MONTH FROM production_start_time)

Q: Which flavour caused the most wastage this month?
SQL: SELECT flavour, SUM(wastage_kg) AS total_wastage FROM wastage_records WHERE production_start_time >= DATE_TRUNC('month', CURRENT_DATE) GROUP BY flavour ORDER BY total_wastage DESC LIMIT 1

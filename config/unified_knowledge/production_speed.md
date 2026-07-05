# TABLE: production_speed_details_data

## PURPOSE
Stores minute-level and 5-minute interval speed measurements for packing machines. Used for machine speed trend analysis and OEE calculation metrics.

## COLUMNS (COMPLETE LIST)
- `production_speed`: The average pre-calculated speed. Use for simple/approximate queries.
- `production_speed_bpm`: JSONB array containing minute-by-minute actual speed values (e.g., `[100, 102, 98]`). Use for precise minute-level analysis or net efficiency.
- `active`: Flag/status of the speed sensor active state.
- `loop_id`: ID of the production line.
- `machine_id`: Foreign key to machines table.
- `variant`: Product variant type.
- `grammage`: Product grammage SKU.
- `customer_id`: ID of the customer.
- `start_time`: The timestamp of the record. USE THIS FOR ALL DATE FILTERING.
- `end_time`: The end timestamp of the record.

## FORMULAS
- **JSONB Array Unnesting**: To find precise average speed from the `production_speed_bpm` array, you MUST use `jsonb_array_elements_text()` within a lateral join.
  - Example: `SELECT AVG(speed_val::numeric) FROM production_speed_details_data, jsonb_array_elements_text(production_speed_bpm) AS speed_val`
- **Net Efficiency %** = `(AVG(speed_val::numeric) / NULLIF(AVG(o.target_speed), 0)) * 100` (Requires joining `oee_details_data o` ON `machine_id` and `start_time` to get `target_speed`)

## JOIN RULES
- To join with machines: `production_speed_details_data JOIN machines ON production_speed_details_data.machine_id = machines.id` (NEVER join on `id`)
- To join with lines: `production_speed_details_data JOIN gmiiot_lines ON production_speed_details_data.loop_id = gmiiot_lines.loop_id`

## FORBIDDEN PATTERNS
- ✗ NEVER average the pre-computed average columns without unnesting the array first for precise calculations.
- ✗ NEVER invent a `plant_id` column.

## FILTERING & OUTLIERS
- Date filtering MUST use `start_time`.

## WORKED EXAMPLES

Q: Average speed for machine 3 on YYYY-MM-DD
SQL: SELECT AVG(value::numeric) AS speed_bpm FROM production_speed_details_data, jsonb_array_elements_text(production_speed_bpm) AS value WHERE machine_id = 3 AND start_time::date = 'YYYY-MM-DD'

Q: What is the highest average BPM recorded in a single hour this month?
SQL: SELECT DATE_TRUNC('hour', start_time) AS hr, AVG(value::numeric) AS speed_bpm FROM production_speed_details_data, jsonb_array_elements_text(production_speed_bpm) AS value WHERE start_time >= DATE_TRUNC('month', CURRENT_DATE) GROUP BY DATE_TRUNC('hour', start_time) ORDER BY speed_bpm DESC LIMIT 1

Q: What is the net efficiency for machine 14 today?
SQL: SELECT (AVG(value::numeric) / NULLIF(AVG(o.target_speed), 0)) * 100 AS net_efficiency FROM production_speed_details_data p JOIN oee_details_data o ON p.machine_id = o.machine_id AND p.start_time = o.start_time, jsonb_array_elements_text(p.production_speed_bpm) AS value WHERE p.machine_id = 14 AND p.start_time BETWEEN CURRENT_DATE AND CURRENT_DATE + interval '1 day' - interval '1 second'

Q: Is machine 14 running above or below target speed?
SQL: SELECT AVG(value::numeric) AS actual_speed, AVG(o.target_speed) AS target_speed FROM production_speed_details_data p JOIN oee_details_data o ON p.machine_id = o.machine_id AND p.start_time = o.start_time, jsonb_array_elements_text(p.production_speed_bpm) AS value WHERE p.machine_id = 14 AND p.start_time >= CURRENT_DATE

Q: Speed trend over the last 7 days
SQL: SELECT DATE_TRUNC('day', start_time) AS day, AVG(value::numeric) AS speed_bpm FROM production_speed_details_data, jsonb_array_elements_text(production_speed_bpm) AS value WHERE start_time >= CURRENT_DATE - interval '7 days' GROUP BY DATE_TRUNC('day', start_time) ORDER BY day ASC

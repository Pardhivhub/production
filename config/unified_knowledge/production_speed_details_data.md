# TABLE: production_speed_details_data
# VERIFIED AGAINST LIVE DATABASE SCHEMA

## PURPOSE
Stores JSON arrays of machine speeds measured over time (usually every 5 minutes during a run).

## COLUMNS
- `machine_id`: INTEGER — machine ID.
- `machine_name`: TEXT — machine name. USE DIRECTLY, no JOIN needed.
- `variant`: TEXT — product variant. USE DIRECTLY, no JOIN needed.
- `grammage`: NUMERIC — SKU weight. USE DIRECTLY, no JOIN needed.
- `start_time`: TIMESTAMP — time bucket start.
- `production_speed_bpm`: JSONB — array of speeds (e.g. `[80.0, 81.0, 80.5]`).

## JSON UNNESTING (CRITICAL)
- The speed is stored inside the JSONB column `production_speed_bpm`.
- ✗ NEVER use `AVG(p.speed)` or `AVG(production_speed)`.
- ✓ YOU MUST UNNEST the array using `CROSS JOIN LATERAL jsonb_array_elements_text(production_speed_bpm) AS speed(value)` and then take `AVG(speed.value::numeric)`.

## JOIN RULES
- ✗ NEVER join `oee_details_data`, `ega_details_data`, `variant`, or `gsm_usage_details`.
- All required columns (`variant`, `grammage`, `machine_name`) are ALREADY in this table.

## EXAMPLES

Q: Average production speed by variant and grammage
SQL: SELECT variant, grammage, AVG(speed.value::numeric) AS avg_speed_bpm FROM production_speed_details_data psd CROSS JOIN LATERAL jsonb_array_elements_text(psd.production_speed_bpm) AS speed(value) GROUP BY variant, grammage ORDER BY avg_speed_bpm DESC

Q: Average production speed for machine 5 this month
SQL: SELECT machine_id, machine_name, AVG(speed.value::numeric) AS avg_speed_bpm FROM production_speed_details_data psd CROSS JOIN LATERAL jsonb_array_elements_text(psd.production_speed_bpm) AS speed(value) WHERE machine_id = 5 AND start_time >= DATE_TRUNC('month', CURRENT_DATE) GROUP BY machine_id, machine_name

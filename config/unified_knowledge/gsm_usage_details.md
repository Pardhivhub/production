# TABLE: gsm_usage_details
# VERIFIED AGAINST LIVE DATABASE SCHEMA

## PURPOSE
Stores GSM material usage details shift-wise including starting and ending weights for each material and vendor.
Used to calculate vendor-wise material consumption.

## COLUMNS (COMPLETE LIST — VERIFIED)
- `id`: INTEGER — primary key.
- `material_description`: VARCHAR — description of the material used.
- `vendor`: VARCHAR — vendor supplying the material.
- `weight_type`: VARCHAR — 'Starting Weight' or 'Ending Weight'.
- `weight`: NUMERIC — weight measurement in kg.
- `date`: TIMESTAMP — date and time of the measurement. USE THIS FOR DATE FILTERING (NOT start_time).
- `shift`: VARCHAR — shift identifier (e.g. 'A', 'B', 'C').
- `batch_code`: VARCHAR — batch code for the material.
- `creation_date`: TIMESTAMP — record creation date.
- `update_date`: TIMESTAMP — last update date.

## FORMULAS
- **GSM Consumption** = `GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END))`

## JOIN RULES
- This table does NOT have `machine_id` or `loop_id`. Usually queried independently.
- ✗ NEVER join `gsm_usage_details` to `ega_details_data` or `oee_details_data`.

## FORBIDDEN PATTERNS
- ✗ NEVER sum the `weight` column directly — MUST pivot on `weight_type`.
- ✗ NEVER use `start_time` for date filtering — use `date` instead.

## WORKED EXAMPLES

Q: GSM consumption by vendor
SQL: SELECT vendor, GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END)) AS gsm_consumption_kg FROM gsm_usage_details GROUP BY vendor ORDER BY gsm_consumption_kg DESC

Q: GSM consumption by vendor this month
SQL: SELECT vendor, GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END)) AS gsm_consumption_kg FROM gsm_usage_details WHERE date >= DATE_TRUNC('month', CURRENT_DATE) GROUP BY vendor ORDER BY gsm_consumption_kg DESC

Q: GSM consumption for shift A today
SQL: SELECT vendor, GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END)) AS gsm_consumption_kg FROM gsm_usage_details WHERE date >= CURRENT_DATE AND shift = 'A' GROUP BY vendor ORDER BY gsm_consumption_kg DESC

Q: Which vendor supplied the most material last month?
SQL: SELECT vendor, GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END)) AS gsm_consumption_kg FROM gsm_usage_details WHERE date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') AND date < DATE_TRUNC('month', CURRENT_DATE) GROUP BY vendor ORDER BY gsm_consumption_kg DESC LIMIT 1

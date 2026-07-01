# TABLE: gsm_usage_details

## PURPOSE
Stores GSM material usage details shift-wise including starting and ending weights for each material and vendor. Used to calculate vendor-wise material consumption.

## COLUMNS (COMPLETE LIST)
- `weight_type`: Indicates if the record is a 'Starting Weight' or 'Ending Weight'.
- `weight`: The weight measurement in kg.
- `vendor`: The name of the vendor supplying the material.
- `date`: The date of the measurement.

## FORMULAS
- **GSM Consumption** = `GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END))`

## JOIN RULES
- Usually queried independently. Does not have machine_id or loop_id.

## FORBIDDEN PATTERNS
- ✗ NEVER sum the `weight` column directly without pivoting on `weight_type`.
- ✗ NEVER join with `ega_details_data` or `oee_details_data`.

## WORKED EXAMPLES

Q: GSM consumption by vendor
SQL: SELECT vendor, GREATEST(0, SUM(CASE WHEN weight_type='Starting Weight' THEN weight ELSE 0 END) - SUM(CASE WHEN weight_type='Ending Weight' THEN weight ELSE 0 END)) AS gsm_consumption FROM gsm_usage_details GROUP BY vendor ORDER BY gsm_consumption DESC

Q: Total theoretical pack weight vs actual total weight
SQL: SELECT ((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0)) * 100 AS ega_percent FROM ega_details_data

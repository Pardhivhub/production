# TABLE: oee_details_data
# VERIFIED AGAINST LIVE DATABASE SCHEMA

## PURPOSE
Stores hourly machine-wise manufacturing status, run durations, downtime, speed, production output, failed bags, and rejections.
Can be aggregated by shift, date, line, machine, and grammage.

## COLUMNS (COMPLETE LIST — VERIFIED)
- `machine_id`: INTEGER — machine ID.
- `machine_name`: TEXT — machine name. USE DIRECTLY, no JOIN needed.
- `loop_id`: INTEGER — production loop/line ID.
- `loop_name`: TEXT — loop/line name. USE DIRECTLY, no JOIN needed.
- `plant_unit`: TEXT — plant unit identifier.
- `preset_no`: NUMERIC — preset number.
- `grammage`: NUMERIC — SKU weight in grams. Compare NUMERICALLY (e.g. `grammage = 100`), never with 'g' suffix.
- `variant`: TEXT — product variant (e.g. 'Ridge Cut'). Use ILIKE for matching.
- `start_time`: TIMESTAMP — start of the hourly record. USE FOR ALL DATE FILTERING.
- `end_time`: TIMESTAMP — end of the hourly record.
- `run_duration`: NUMERIC — actual running duration in minutes. (Summable)
- `downtime_mins`: NUMERIC — total downtime in minutes. (Summable)
- `good_bags`: BIGINT — accepted product count in bags. (Summable)
- `failed_bags`: BIGINT — rejected count during run. (Summable)
- `overlimit_count`: NUMERIC — rejections due to weight/size exceeding limit. (Summable)
- `empty_bags`: NUMERIC — count of empty bags. (Summable)
- `laminate_wastage`: NUMERIC — material wastage. (Summable)
- `target_speed`: INTEGER — planned speed in bags/minute.
- `total_on_time`: NUMERIC — total on time in minutes.
- `total_off_time`: NUMERIC — total off time in minutes.
- `total_stop_time`: NUMERIC — total stop time in minutes.
- `jaw_jam_error`: NUMERIC — jaw jam downtime minutes. (Summable)
- `jam_error`: NUMERIC — jam downtime minutes. (Summable)
- `fmd_error`: NUMERIC — FMD error downtime minutes. (Summable)
- `splice_error`: NUMERIC — splice error downtime minutes. (Summable)
- `dump_error`: NUMERIC — dump error downtime minutes. (Summable)
- `print_check_err`: NUMERIC — print check error downtime minutes. (Summable)
- `reg_mark_err`: NUMERIC — registration mark error downtime minutes. (Summable)
- `tube_change`: NUMERIC — tube change time in minutes. (Summable)
- `interface_error`: NUMERIC — interface error downtime minutes. (Summable)
- `low_product_time`: NUMERIC — low product time in minutes. (Summable)
- `clock_error`: NUMERIC — clock error minutes. (Summable)
- `pack_ega_limit`: NUMERIC — EGA limit for packing.
- `proper`: BIGINT — number of properly counted bags.
- `under_weight`: NUMERIC — under weight count.
- `total_stop_count`: NUMERIC — total stop count.
- `bag_length`, `film_width`, `gsm`, `one_bag_area`, `one_bag_wt`: Physical bag parameters.
- `empty_bags_kg`, `failed_bags_kg`, `jam_error_kg`, `jaw_jam_error_kg`, `fmd_error_kg`, `splice_error_kg`, `dump_error_kg`, `print_check_err_kg`, `reg_mark_err_kg`: Kilogram equivalents for losses.

## DEFINITIONS
- **failed_bags**: Runtime rejections on the machine (e.g. film tears, jam).
- **overlimit_count**: Quality rejections where the bag was packed but exceeded target weight limit.

## FORMULAS (must be calculated dynamically — NOT stored)
- **Availability %** = `(SUM(run_duration) / NULLIF(SUM(run_duration) + SUM(downtime_mins), 0)) * 100`
  - Alternative: `((SUM(1)*60 - SUM(downtime_mins)) / NULLIF(SUM(1)*60, 0)) * 100`
- **Performance %** = `(SUM(good_bags) / NULLIF(SUM(run_duration), 0)) / NULLIF(AVG(target_speed), 0) * 100`
- **Quality %** = `CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100 - ((SUM(overlimit_count) + SUM(failed_bags)) / NULLIF(SUM(good_bags), 0)) * 100 END`
- **Overall OEE %** = `(Availability * Performance * Quality) / 10000`
- **Total Error Count** = `SUM(jaw_jam_error) + SUM(jam_error) + SUM(fmd_error) + SUM(splice_error) + SUM(dump_error) + SUM(print_check_err) + SUM(reg_mark_err)`
- **MTTR** = `SUM(downtime_mins) / NULLIF(SUM(jaw_jam_error)+SUM(jam_error)+SUM(fmd_error)+SUM(splice_error)+SUM(dump_error)+SUM(print_check_err)+SUM(reg_mark_err), 0)`

## JOIN RULES
- ✓ `machine_name` is ALREADY in the table — NO JOIN to `machines` needed.
- ✓ `loop_name` is ALREADY in the table — NO JOIN to `gmiiot_lines` needed.

## FORBIDDEN PATTERNS
- ✗ NEVER SELECT columns named `oee`, `availability`, `performance`, `quality_percentage` — they do NOT exist.
- ✗ NEVER use `AVG(oee)` — calculate from formulas above.
- ✗ NEVER join `oee_details_data` to `wastage_records` directly.
- ✗ NEVER add a `plant_id` column — it does NOT exist here.
- ✗ NEVER filter grammage with a 'g' suffix — grammage is NUMERIC.
- ✗ NEVER JOIN machines just to get machine_name — it's already in the table.
- ✗ This table has NO `shift` column — use HOUR extraction from `start_time` for shift filtering.

## WORKED EXAMPLES

Q: What is the OEE for machine 4 today?
SQL: SELECT machine_name, (((SUM(good_bags)/NULLIF(SUM(run_duration),0))/NULLIF(AVG(target_speed),0)*100) * ((SUM(run_duration))/NULLIF(SUM(run_duration)+SUM(downtime_mins),0)*100) * (CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100-((SUM(overlimit_count)+SUM(failed_bags))/NULLIF(SUM(good_bags),0))*100 END)) / 10000 AS oee_percent FROM oee_details_data WHERE machine_id = 4 AND start_time >= CURRENT_DATE AND start_time < CURRENT_DATE + INTERVAL '1 day' GROUP BY machine_id, machine_name

Q: Show availability for each machine yesterday
SQL: SELECT machine_id, machine_name, (SUM(run_duration) / NULLIF(SUM(run_duration) + SUM(downtime_mins),0)) * 100 AS availability_percent FROM oee_details_data WHERE start_time >= CURRENT_DATE - INTERVAL '1 day' AND start_time < CURRENT_DATE GROUP BY machine_id, machine_name ORDER BY availability_percent DESC

Q: Highest downtime machine this week
SQL: SELECT machine_id, machine_name, SUM(downtime_mins) AS total_downtime_mins FROM oee_details_data WHERE start_time >= DATE_TRUNC('week', CURRENT_DATE) GROUP BY machine_id, machine_name ORDER BY total_downtime_mins DESC LIMIT 1

Q: Quality percent for all machines
SQL: SELECT machine_id, machine_name, CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100-((SUM(overlimit_count)+SUM(failed_bags))/NULLIF(SUM(good_bags),0))*100 END AS quality_percent FROM oee_details_data GROUP BY machine_id, machine_name ORDER BY quality_percent DESC

Q: Which error type caused the most downtime today?
SQL: SELECT 'Jaw Jam' AS error_type, SUM(jaw_jam_error) AS total_mins FROM oee_details_data WHERE start_time >= CURRENT_DATE UNION ALL SELECT 'Jam', SUM(jam_error) FROM oee_details_data WHERE start_time >= CURRENT_DATE UNION ALL SELECT 'FMD', SUM(fmd_error) FROM oee_details_data WHERE start_time >= CURRENT_DATE UNION ALL SELECT 'Splice', SUM(splice_error) FROM oee_details_data WHERE start_time >= CURRENT_DATE UNION ALL SELECT 'Dump', SUM(dump_error) FROM oee_details_data WHERE start_time >= CURRENT_DATE UNION ALL SELECT 'Print Check', SUM(print_check_err) FROM oee_details_data WHERE start_time >= CURRENT_DATE ORDER BY total_mins DESC LIMIT 1

Q: Machine 7 morning shift performance today
SQL: SELECT machine_name, (SUM(good_bags) / NULLIF(SUM(run_duration),0)) / NULLIF(AVG(target_speed),0) * 100 AS performance_percent FROM oee_details_data WHERE machine_id = 7 AND start_time >= CURRENT_DATE AND EXTRACT(HOUR FROM start_time) >= 6 AND EXTRACT(HOUR FROM start_time) < 14 GROUP BY machine_id, machine_name

Q: Total empty bags produced today
SQL: SELECT SUM(empty_bags) AS total_empty_bags FROM oee_details_data WHERE start_time >= CURRENT_DATE AND start_time < CURRENT_DATE + INTERVAL '1 day'

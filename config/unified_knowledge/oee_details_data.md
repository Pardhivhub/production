# TABLE: oee_details_data

## PURPOSE
Stores hourly machine-wise manufacturing status, run durations, downtime, speed, production output, failed bags, and rejections. Can be aggregated by shift, date, line, machine, and grammage.

## COLUMNS (COMPLETE LIST)
- `run_duration`: Actual running duration in minutes. (Summable)
- `downtime_mins`: Total downtime in minutes. (Summable)
- `good_bags`: Total accepted product count in bags. (Summable)
- `failed_bags`: Total rejected count during run. (Summable)
- `overlimit_count`: Rejections due to weight/size exceeding limit. (Summable)
- `empty_bags`: Count of empty bags.
- `laminate_wastage`: Material wastage.
- `target_speed`: Planned speed in bags/minute.
- `jaw_jam_error`, `jam_error`, `fmd_error`, `splice_error`, `dump_error`, `print_check_err`, `reg_mark_err`, `tube_change`, `interface_error`, `low_product_time`: Specific downtime error minutes. (Summable)
- `machine_id`: Foreign key to machines table.
- `loop_id`: ID of the production line.
- `start_time`: The timestamp of the record. USE THIS FOR ALL DATE FILTERING.
- `end_time`: The end timestamp of the record hour.
- `grammage`: SKU weight category.
- `variant`: Product variant type.

## FORMULAS
OEE calculations are NOT pre-stored. You must compute Availability, Performance, Quality, and OEE dynamically using sums.
- **Availability %** = `(SUM(1)*60 - SUM(downtime_mins)) / NULLIF(SUM(1)*60, 0) * 100`  (assuming 60 mins per hour row)
- **Performance %** = `(SUM(good_bags) / NULLIF((SUM(1)*60 - SUM(downtime_mins)),0)) / NULLIF(AVG(target_speed),0) * 100`
- **Quality %** = `CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100 - ((SUM(overlimit_count) + SUM(failed_bags)) / NULLIF(SUM(good_bags), 0)) * 100 END`
- **Overall OEE %** = `(Availability * Performance * Quality) / 10000`
- **Total Error Count** = `SUM(jaw_jam_error) + SUM(jam_error) + SUM(fmd_error) + SUM(splice_error) + SUM(dump_error) + SUM(print_check_err) + SUM(reg_mark_err)`

## JOIN RULES
- To join with machines: `oee_details_data JOIN machines ON oee_details_data.machine_id = machines.machine_id` (NEVER join on `id`)
- To join with lines: `oee_details_data JOIN gmiiot_lines ON oee_details_data.loop_id = gmiiot_lines.loop_id`

## FORBIDDEN PATTERNS
- ✗ NEVER select `oee`, `availability`, or `quality_percentage` columns (they do not exist).
- ✗ NEVER use `AVG(oee)`. You MUST calculate using the formulas above.
- ✗ NEVER join `oee_details_data` to `wastage_records` directly.
- ✗ NEVER invent a `plant_id` column.

## FILTERING & OUTLIERS
- Date filtering MUST use `start_time`.

## WORKED EXAMPLES

Q: What is the OEE for machine 4 today?
SQL: SELECT (((SUM(good_bags)/NULLIF((SUM(1)*60-SUM(downtime_mins)),0))/NULLIF(AVG(target_speed),0)*100) * ((SUM(1)*60-SUM(downtime_mins))/NULLIF(SUM(1)*60,0)*100) * (CASE WHEN SUM(good_bags)=0 THEN 0 ELSE 100-((SUM(overlimit_count)+SUM(failed_bags))/NULLIF(SUM(good_bags),0))*100 END)) / 10000 AS oee_percent FROM oee_details_data WHERE machine_id = 4 AND start_time BETWEEN '2026-07-01' AND '2026-07-01 23:59:59'

Q: Show availability for each machine yesterday
SQL: SELECT m.machine_name, ((SUM(1)*60 - SUM(o.downtime_mins)) / NULLIF(SUM(1)*60,0)) * 100 AS availability FROM oee_details_data o JOIN machines m ON o.machine_id = m.machine_id WHERE o.start_time BETWEEN '2026-06-30' AND '2026-06-30 23:59:59' GROUP BY m.machine_name

Q: Highest downtime machine this week
SQL: SELECT m.machine_name, SUM(o.downtime_mins) AS total_downtime FROM oee_details_data o JOIN machines m ON o.machine_id = m.machine_id WHERE o.start_time >= CURRENT_DATE - INTERVAL '7 days' GROUP BY m.machine_name ORDER BY total_downtime DESC LIMIT 1

Q: Quality percent for all machines
SQL: SELECT m.machine_name, CASE WHEN SUM(o.good_bags)=0 THEN 0 ELSE 100-((SUM(o.overlimit_count)+SUM(o.failed_bags))/NULLIF(SUM(o.good_bags),0))*100 END AS quality_pct FROM oee_details_data o JOIN machines m ON o.machine_id = m.machine_id GROUP BY m.machine_name

# DIMENSION TABLES: machines, gmiiot_lines, gmiiot_plants
# VERIFIED AGAINST LIVE DATABASE SCHEMA

## ⚠️ CRITICAL: machines JOIN IS RARELY NEEDED
- `ega_details_data`, `oee_details_data`, and `production_speed_details_data` already have `machine_name` and `loop_name` columns built in.
- Only JOIN these dimension tables when you specifically need columns that don't exist in the fact table.

---

## TABLE: machines
Master register catalog for all packing machines.
- **Columns**: `id` (INTEGER — Primary Key), `machine_name` (VARCHAR), `loop_id` (INTEGER), `customer_id`, `active`, `start_date`, `end_date`, `location_id`, `estimated_cycle_time`, `carrier_id`, `section_id`, `comments`.
- **Join Rule**: `JOIN machines m ON t.machine_id = m.id` (Primary Key is `id`, NOT `machine_id`).
- **Filter**: When user asks for "machine 1" or "PM 1", filter on `machine_id = 1` OR `machine_name ILIKE '%Machine-1%'` directly on the fact table — no JOIN needed.
- ✗ NEVER join using a column named `machine_id` on the machines table — it does NOT exist. The PK is `id`.

---

## TABLE: gmiiot_lines
Master register catalog for production lines/loops.
- **Columns**: `id` (INTEGER — Primary Key), `line_name` (VARCHAR), `plant_id` (INTEGER).
- **Join Rule**: `JOIN gmiiot_lines l ON t.loop_id = l.id`
- **Filtering**: Use `l.line_name ILIKE '%Line 1%'`
- ✗ NEVER use `loop_id` or `loop_name` as columns on this table — PK is `id`, name column is `line_name`.

---

## TABLE: gmiiot_plants
Master register catalog for plants.
- **Columns**: `plant_id` (INTEGER — Primary Key), `plant_name` (VARCHAR).
- **Join Rule**: `JOIN gmiiot_plants p ON w.plant_id = p.plant_id`
- Only `wastage_records` and `gmiiot_lines` have a `plant_id` column.
- To filter `oee_details_data` by plant: join through lines → `oee_details_data JOIN gmiiot_lines l ON oee_details_data.loop_id = l.id JOIN gmiiot_plants p ON l.plant_id = p.plant_id`

---

## FORBIDDEN PATTERNS
- ✗ NEVER assume `machine_name` is missing from `oee_details_data`, `ega_details_data`, or `production_speed_details_data` — it IS there.
- ✗ NEVER join `machines` using a `machine_id` column on machines — its PK is `id`.
- ✗ NEVER use `loop_name` on `gmiiot_lines` — the column is `line_name`.
- ✗ NEVER use `gmiiot_lines.loop_id` — the PK column name is `id`.

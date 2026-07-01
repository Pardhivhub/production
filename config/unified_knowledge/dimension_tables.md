# DIMENSION TABLES: machines, gmiiot_lines, gmiiot_plants, flavours

## TABLE: machines
Master register catalog for all packing machines.
- **Columns**: `machine_id` (Integer), `machine_name` (e.g. 'Machine-1', 'Machine-2').
- **Join Rules**: 
  - ALWAYS join using `machine_id` (e.g., `JOIN machines ON ega_details_data.machine_id = machines.machine_id`).
  - NEVER join using `id`.
- **Filtering**: When a user asks for "machine 1" or "PM 1", filter on `machines.machine_name ILIKE '%Machine-1%'` or `machines.machine_id = 1`.

## TABLE: gmiiot_lines
Master register catalog for production lines/loops.
- **Columns**: `loop_id` (Integer), `loop_name` (e.g. 'Line 1'), `plant_id`.
- **Join Rules**:
  - `ega_details_data`, `oee_details_data`, and `production_speed_details_data` join to this table using `loop_id`.
  - `wastage_records` joins to this table using `line_id = gmiiot_lines.loop_id`.
- **Filtering**: Use `loop_name ILIKE '%Line 1%'`.

## TABLE: gmiiot_plants
Master register catalog for plants.
- **Columns**: `plant_id`, `plant_name`.
- **Join Rules**:
  - Only `wastage_records` and `gmiiot_lines` have a `plant_id`.
  - To filter `oee_details_data` by plant, you must join through lines: `oee_details_data JOIN gmiiot_lines ON oee_details_data.loop_id = gmiiot_lines.loop_id JOIN gmiiot_plants ON gmiiot_lines.plant_id = gmiiot_plants.plant_id`.

## TABLE: flavours
Master catalog for product flavours and variants.
- **Columns**: `flavour_id`, `flavour_name` (e.g. 'Salted', 'Cheese Chilli'), `variant_name` (e.g. 'Ridge Cut', 'Flat Cut').
- **Join Rules**: Can be used to map flavours to variants.

## FORBIDDEN PATTERNS
- ✗ NEVER assume `machine_name` exists in `oee_details_data` or `ega_details_data`. It ONLY exists in `machines`.
- ✗ NEVER assume `loop_id` exists in `machines`. It ONLY exists in `gmiiot_lines`.

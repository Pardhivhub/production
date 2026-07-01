# GLOBAL RULES: Cross-cutting rules for all tables

## 1. POSTGRES SYNTAX & NULL SAFETY
- **Case Insensitive Matching**: Always use `ILIKE` instead of `=` for matching string attributes (e.g. `variant ILIKE '%Ridge Cut%'`).
- **Grouping by Time**: When grouping by time periods, use `DATE_TRUNC('hour', start_time)`, `DATE_TRUNC('day', start_time)`, etc.
- **Division Safety**: ALWAYS wrap division denominators in `NULLIF` to avoid division-by-zero crashes. E.g. `(a / NULLIF(b, 0))`.
- **COALESCE**: Use `COALESCE(value, 0)` on nullable numeric columns before arithmetic.

## 2. SORTING AND RANKING
- When querying "highest", "most", "worst OEE", or "top", use `ORDER BY metric DESC` and `LIMIT 1`.
- When querying "lowest", "least", or "best OEE", use `ORDER BY metric ASC` and `LIMIT 1`.
- **Availability Inversion**: "Highest availability" means "lowest downtime" (`ORDER BY SUM(downtime_mins) ASC`). "Lowest availability" means "highest downtime" (`ORDER BY SUM(downtime_mins) DESC`).

## 3. "ALL" OR "EACH" QUERIES
- ✗ NEVER add a hardcoded `WHERE machine_id = N` filter if the user asks for "all machines", "each machine", "every machine", or "grouped by machine".
- When asked to group by a dimension, just add `GROUP BY machine_id, machine_name` (or whatever dimension).

## 4. COMPARE QUERIES (MULTI-MACHINE)
- If the user asks to "compare machine 4 and machine 7", you must:
  1. Add `WHERE machine_id IN (4, 7)`
  2. Add `GROUP BY machine_id, machine_name`
  3. Add `ORDER BY machine_id`
- Each machine must appear as its own row. NEVER return a single combined row for a comparison.

## 5. SCHEMA PREFIX
- ALWAYS prefix table names with `` in the FROM clause (e.g., `FROM ega_details_data`).

## WORKED EXAMPLES

Q: Compare EGA percent between machine 7 and machine 8
SQL: SELECT m.machine_name, ((SUM(e.t_weight) - SUM(e.theoretical_pack_weight)) / NULLIF(SUM(e.t_weight),0)) * 100 AS ega_percent FROM ega_details_data e JOIN machines m ON e.machine_id = m.machine_id WHERE e.machine_id IN (7, 8) GROUP BY m.machine_name ORDER BY m.machine_name

Q: Show EGA percent grouped by machine
SQL: SELECT m.machine_name, ((SUM(e.t_weight) - SUM(e.theoretical_pack_weight)) / NULLIF(SUM(e.t_weight),0)) * 100 AS ega_percent FROM ega_details_data e JOIN machines m ON e.machine_id = m.machine_id GROUP BY m.machine_name

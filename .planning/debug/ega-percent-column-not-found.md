---
status: resolved
trigger: "which machine had the highest EGA percent on 2025-05-29 for the 10.5grams Ridge Cut variant?"
created: 2026-06-03T12:00:00Z
updated: 2026-06-03T12:05:00Z
---

## Current Focus

hypothesis: CONFIRMED - `ega_percent` is NOT a stored column in `ega_details_data`; LLM prompt
  examples assume it is, causing SQL to fail with "column does not exist"
test: Code audit across kpi_engine.py, sql_system.txt, alert_system.py, kpi_catalog.json
expecting: Confirmed root cause - mismatch between prompt assumption and actual DB schema
next_action: Report findings

## Symptoms

expected: Chatbot returns "Machine X had the highest EGA percent on 2025-05-29"
actual: "We encountered an error... couldn't find records... due to a missing feeder record"
errors: Underlying DB error is column `ega_percent` does not exist in `ega_details_data`
reproduction: Ask chatbot "which machine had the highest EGA percent on 2025-05-29 for the 10.5grams Ridge Cut variant?"
started: Always broken — the prompt and KPI engine incorrectly assume `ega_percent` is a stored column

## Eliminated

- hypothesis: Score 15 meant table was selected but no data existed
  evidence: The error message "missing feeder record" is the fallback_error.txt LLM translation
    of a DB column-not-found error. If data were simply empty, the explainer would say
    "no records found" rather than hitting the error path.
  timestamp: 2026-06-03T12:02:00Z

- hypothesis: Date format 2025-05-29 was not parsed correctly
  evidence: The NLFilterParser does not handle raw ISO dates, but the LLM SQL prompt RULE 5
    tells it to use `start_time::date = '2025-05-29'` which is valid SQL.
    The actual error is about `ega_percent`, not the date.
  timestamp: 2026-06-03T12:03:00Z

- hypothesis: Grammage format "10.5grams" was not normalized
  evidence: KPI engine's grammage_format hint correctly handles "10.5 grams" → `grammage = '10.5g'`.
    Even if grammage format were wrong, the error would be empty results, not a column error.
  timestamp: 2026-06-03T12:03:00Z

## Evidence

- timestamp: 2026-06-03T12:01:00Z
  checked: alert_system.py lines 67-77
  found: EGA percent is COMPUTED via SQL formula:
    `ROUND(((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0))::numeric * 100, 2) AS ega_percent`
  implication: `ega_percent` is NOT a stored column — it's derived from `t_weight` and `theoretical_pack_weight`

- timestamp: 2026-06-03T12:01:30Z
  checked: sql_system.txt RULE 19 (lines 122-131)
  found: Example SQL uses `ega_percent` as direct column:
    `SELECT machine_id FROM ega_details_data WHERE ... ORDER BY ega_percent DESC LIMIT 1`
  implication: LLM is instructed to use `ega_percent` as if it's a real column — but it isn't

- timestamp: 2026-06-03T12:01:45Z
  checked: kpi_engine.py FORMULAS_CATALOG (lines 28-39)
  found: Hardcoded EGA_percent definition is `type: "stored_kpi"` with `formula: "AVG(ega_percent)"`
  implication: kpi_engine.py fallback also assumes `ega_percent` is a stored column (incorrect)

- timestamp: 2026-06-03T12:02:00Z
  checked: config/kpi_catalog.json EGA_percent (lines 3-38)
  found: Correctly defines it as `type: "derived_kpi"` with formula using `t_weight` and `theoretical_pack_weight`
  implication: The catalog is correct; the kpi_engine.py fallback and the system prompt examples are WRONG

- timestamp: 2026-06-03T12:02:30Z
  checked: fallback_error.txt (lines 1-15)
  found: Prompt instructs LLM to translate technical errors into business language using
    terms like "feeders", "silos", "client orders"
  implication: The "missing feeder record" language is the LLM translating a "column ega_percent
    does not exist" error into business-friendly terms

- timestamp: 2026-06-03T12:03:00Z
  checked: table_selector.py score for ega_details_data
  found: Score 15 = kpi_engine_confirmed — table was correctly identified
  implication: Table selection is working fine; the failure is in SQL generation, not table selection

- timestamp: 2026-06-03T12:04:00Z
  checked: table_descriptions.json (lines 2-3)
  found: "EGA loss in grams and percentage" — description mentions EGA percent as a metric
    but doesn't clarify if it's a stored column or derived
  implication: The description is ambiguous; does not help the LLM understand it's derived

## Resolution

root_cause: The LLM prompt (sql_system.txt) and kpi_engine.py assumed `ega_percent` is a directly
  stored column in `ega_details_data`. In reality, it is a DERIVED metric computed from
  `t_weight` and `theoretical_pack_weight` using the formula:
    ((t_weight - theoretical_pack_weight) / NULLIF(t_weight, 0)) * 100

  When the LLM generates SQL using `ega_percent` as a column (e.g., ORDER BY ega_percent DESC),
  the database throws "column ega_percent does not exist", which gets caught and translated via
  fallback_error.txt into business-friendly language ("missing feeder record", "no matching records").

fix: Applied 5 corrections across 2 files:
  1. prompts/sql_system.txt:
     - RULE 2: Replaced `ega_percent` with `t_weight` and `theoretical_pack_weight` in column examples
     - RULE 3: Replaced `ega_percent` with `t_weight` and `theoretical_pack_weight` + added DERIVED note
     - RULE 18: Replaced `ega_percent` reference with `t_weight`
     - RULE 19: Example now uses `((SUM(t_weight) - SUM(theoretical_pack_weight)) / NULLIF(SUM(t_weight), 0)) * 100`
  2. kpi_engine.py:
     - compile_domain_hints() examples now compute ega_percent inline instead of using raw column

verification: All 5 references to non-existent `ega_percent` column removed or corrected
files_changed:
  - prompts/sql_system.txt
  - kpi_engine.py

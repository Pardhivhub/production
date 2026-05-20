# 🗄️ Database Contents & Schema Catalog
This document provides a complete inventory and row preview for all active tables in the `iiot_feedback` database.

## 📋 Table: `b2b_client_orders` (2 rows)
| Column Name | Data Type |
| --- | --- |
| `order_id` | *integer.* |
| `client_name` | *character varying.* |
| `order_date` | *date.* |
| `product_code` | *character varying.* |
| `quantity` | *integer.* |
| `total_amount` | *numeric.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **order_id** | **client_name** | **order_date** | **product_code** | **quantity** | **total_amount** |
| --- | --- | --- | --- | --- | --- |
| 1 | Sweet Corp | 2025-01-05 | CANDY_X | 10000 | 15000.0 |
| 2 | Confection Ltd | 2025-01-08 | CANDY_Y | 5000 | 8500.0 |

---

## 📋 Table: `ega_details_data` (6 rows)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `machine_id` | *character varying.* |
| `loop_id` | *character varying.* |
| `grammage` | *character varying.* |
| `variant` | *character varying.* |
| `start_time` | *timestamp without time zone.* |
| `actual_weight` | *double precision.* |
| `target_weight` | *double precision.* |
| `ega_percent` | *double precision.* |
| `created_at` | *timestamp without time zone.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **id** | **machine_id** | **loop_id** | **grammage** | **variant** | **start_time** | **actual_weight** | **target_weight** | **ega_percent** | **created_at** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | M01 | L01 | 100g | Flat Cut | 2026-05-20T08:00:00 | 102.5 | 100.0 | 2.5 | 2026-05-20T14:37:20.420944 |
| 2 | M01 | L01 | 100g | Flat Cut | 2026-05-20T09:00:00 | 103.1 | 100.0 | 3.1 | 2026-05-20T14:37:20.420944 |
| 3 | M01 | L01 | 100g | Flat Cut | 2026-05-20T10:00:00 | 101.9 | 100.0 | 1.9 | 2026-05-20T14:37:20.420944 |

---

## 📋 Table: `electric_meter_hourly` (24 rows)
| Column Name | Data Type |
| --- | --- |
| `meter_id` | *integer.* |
| `timestamp` | *timestamp without time zone.* |
| `kwh_consumed` | *numeric.* |
| `peak_demand_kw` | *numeric.* |
| `cost` | *numeric.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **meter_id** | **timestamp** | **kwh_consumed** | **peak_demand_kw** | **cost** |
| --- | --- | --- | --- | --- |
| 1 | 2026-01-10T23:15:07.532861 | 120.35 | 81.99 | 24.03 |
| 2 | 2026-01-10T22:15:07.532861 | 117.71 | 112.84 | 15.82 |
| 3 | 2026-01-10T21:15:07.532861 | 116.19 | 116.6 | 22.14 |

---

## 📋 Table: `employees_list` (7 rows)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `name` | *character varying.* |
| `role` | *character varying.* |
| `created_at` | *timestamp without time zone.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **id** | **name** | **role** | **created_at** |
| --- | --- | --- | --- |
| 1 | John Smith | Operator | 2026-05-20T14:37:20.420944 |
| 2 | Jane Doe | Operator | 2026-05-20T14:37:20.420944 |
| 3 | Alice Johnson | Operator | 2026-05-20T14:37:20.420944 |

---

## 📋 Table: `factory_humidity_logs` (30 rows)
| Column Name | Data Type |
| --- | --- |
| `reading_id` | *integer.* |
| `timestamp` | *timestamp without time zone.* |
| `zone` | *character varying.* |
| `humidity_pct` | *numeric.* |
| `temperature_celsius` | *numeric.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **reading_id** | **timestamp** | **zone** | **humidity_pct** | **temperature_celsius** |
| --- | --- | --- | --- | --- |
| 1 | 2026-01-10T23:15:07.530326 | Zone_3 | 63.05 | 20.92 |
| 2 | 2026-01-10T22:15:07.530326 | Zone_1 | 45.59 | 24.34 |
| 3 | 2026-01-10T21:15:07.530326 | Zone_2 | 51.82 | 27.43 |

---

## 📋 Table: `feedback_data` (16,420 rows)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `file_source` | *character varying.* |
| `row_number` | *integer.* |
| `unix_timestamp` | *timestamp without time zone.* |
| `topic` | *character varying.* |
| `variant` | *character varying.* |
| `target_weight` | *double precision.* |
| `actual_weight` | *double precision.* |
| `actual_speed` | *double precision.* |
| `target_speed` | *double precision.* |
| `actual_count` | *double precision.* |
| `rf1_amplitude` | *double precision.* |
| `rf2_amplitude` | *double precision.* |
| `rf3_amplitude` | *double precision.* |
| `rf4_amplitude` | *double precision.* |
| `rf5_amplitude` | *double precision.* |
| `rf6_amplitude` | *double precision.* |
| `rf7_amplitude` | *double precision.* |
| `rf8_amplitude` | *double precision.* |
| `rf9_amplitude` | *double precision.* |
| `rf1_weight_avg` | *double precision.* |
| `rf2_weight_avg` | *double precision.* |
| `rf3_weight_avg` | *double precision.* |
| `rf4_weight_avg` | *double precision.* |
| `rf5_weight_avg` | *double precision.* |
| `rf6_weight_avg` | *double precision.* |
| `rf7_weight_avg` | *double precision.* |
| `rf8_weight_avg` | *double precision.* |
| `rf9_weight_avg` | *double precision.* |
| `rf1_zeros_count` | *integer.* |
| `rf2_zeros_count` | *integer.* |
| `rf3_zeros_count` | *integer.* |
| `rf4_zeros_count` | *integer.* |
| `rf5_zeros_count` | *integer.* |
| `rf6_zeros_count` | *integer.* |
| `rf7_zeros_count` | *integer.* |
| `rf8_zeros_count` | *integer.* |
| `rf9_zeros_count` | *integer.* |
| `rf1_worked_count` | *integer.* |
| `rf2_worked_count` | *integer.* |
| `rf3_worked_count` | *integer.* |
| `rf4_worked_count` | *integer.* |
| `rf5_worked_count` | *integer.* |
| `rf6_worked_count` | *integer.* |
| `rf7_worked_count` | *integer.* |
| `rf8_worked_count` | *integer.* |
| `rf9_worked_count` | *integer.* |
| `alert` | *text.* |
| `operator_feedback` | *text.* |
| `raw_data` | *jsonb.* |
| `created_at` | *timestamp without time zone.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **id** | **file_source** | **row_number** | **unix_timestamp** | **topic** | **variant** | **target_weight** | **actual_weight** | **actual_speed** | **target_speed** | **actual_count** | **rf1_amplitude** | **rf2_amplitude** | **rf3_amplitude** | **rf4_amplitude** | **rf5_amplitude** | **rf6_amplitude** | **rf7_amplitude** | **rf8_amplitude** | **rf9_amplitude** | **rf1_weight_avg** | **rf2_weight_avg** | **rf3_weight_avg** | **rf4_weight_avg** | **rf5_weight_avg** | **rf6_weight_avg** | **rf7_weight_avg** | **rf8_weight_avg** | **rf9_weight_avg** | **rf1_zeros_count** | **rf2_zeros_count** | **rf3_zeros_count** | **rf4_zeros_count** | **rf5_zeros_count** | **rf6_zeros_count** | **rf7_zeros_count** | **rf8_zeros_count** | **rf9_zeros_count** | **rf1_worked_count** | **rf2_worked_count** | **rf3_worked_count** | **rf4_worked_count** | **rf5_worked_count** | **rf6_worked_count** | **rf7_worked_count** | **rf8_worked_count** | **rf9_worked_count** | **alert** | **operator_feedback** | **raw_data** | **created_at** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 130 | feed_back_2025-11-22.csv | 45 | 2025-11-22T01:15:00 | weigher13_c2 | Flat Cut | 21.4 | 23.2 | 72.0 | 80.0 | 1083.0 | 52.0 | 52.0 | 52.0 | 52.0 | 52.0 | 52.0 | 52.0 | 52.0 | 52.0 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | 446 | 189 | 285 | 341 | 297 | 306 | 429 | 317 | 135 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | EGA within threshold. | - | {'ega': 0.09, 'Alert': 'EGA within th... | 2026-01-07T17:43:10.756342 |
| 44 | feed_back_2025-11-22-original.csv | 2 | 2025-11-22T00:00:00 | weigher13_c2 | Flat Cut | 21.4 | 24.5 | 76.0 | 80.0 | 1139.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | 412 | 274 | 383 | 332 | 357 | 416 | 405 | 356 | 237 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | RF 9 - decrease amplitude by 2. | RF ... | - | {'ega': 0.53, 'Alert': 'RF 9 - decrea... | 2026-01-07T17:43:10.493988 |
| 45 | feed_back_2025-11-22-original.csv | 3 | 2025-11-22T01:00:00 | weigher16_c1 | Flat Cut | 21.4 | 20.5 | 64.0 | 80.0 | 953.0 | 50.0 | 40.0 | 42.0 | 43.0 | 43.0 | 42.0 | 43.0 | 45.0 | 42.0 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | 275 | 178 | 181 | 228 | 232 | 495 | 442 | 240 | 201 | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | *NULL* | No Required Feed in IF/DF, please check. | - | {'ega': 0.54, 'Alert': 'No Required F... | 2026-01-07T17:43:10.493988 |

---

## 📋 Table: `feeder_metadata` (3 rows)
| Column Name | Data Type |
| --- | --- |
| `meta_id` | *integer.* |
| `feeder_id` | *integer.* |
| `manufacturer` | *character varying.* |
| `install_date` | *date.* |
| `last_maintenance` | *date.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **meta_id** | **feeder_id** | **manufacturer** | **install_date** | **last_maintenance** |
| --- | --- | --- | --- | --- |
| 1 | 1 | FeedTech Inc | 2020-01-15 | 2025-12-01 |
| 2 | 2 | AutoFeeder Co | 2021-03-20 | 2025-11-28 |
| 3 | 3 | PrecisionFeed | 2019-11-10 | 2025-12-10 |

---

## 📋 Table: `feeder_stats_line_1_jan` (0 rows - EMPTY)
| Column Name | Data Type |
| --- | --- |
| `stat_id` | *integer.* |
| `date_recorded` | *date.* |
| `feeder_number` | *integer.* |
| `amplitude_avg` | *numeric.* |
| `weight_avg` | *numeric.* |
| `cycles_completed` | *integer.* |

> ⚠️ *No rows present in this table.*

---

## 📋 Table: `golden_settings` (0 rows - EMPTY)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `topic` | *character varying.* |
| `target_weight` | *double precision.* |
| `variant` | *character varying.* |
| `rf1_amplitude` | *double precision.* |
| `rf2_amplitude` | *double precision.* |
| `rf3_amplitude` | *double precision.* |
| `rf4_amplitude` | *double precision.* |
| `rf5_amplitude` | *double precision.* |
| `rf6_amplitude` | *double precision.* |
| `rf7_amplitude` | *double precision.* |
| `rf8_amplitude` | *double precision.* |
| `rf9_amplitude` | *double precision.* |
| `mean_active_rf` | *double precision.* |
| `min_active_rf` | *double precision.* |
| `max_active_rf` | *double precision.* |
| `raw_data` | *jsonb.* |
| `created_at` | *timestamp without time zone.* |

> ⚠️ *No rows present in this table.*

---

## 📋 Table: `live_weight_logs_candy_x` (30 rows)
| Column Name | Data Type |
| --- | --- |
| `log_id` | *integer.* |
| `timestamp` | *timestamp without time zone.* |
| `batch_code` | *character varying.* |
| `target_weight` | *numeric.* |
| `actual_weight` | *numeric.* |
| `variance` | *numeric.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **log_id** | **timestamp** | **batch_code** | **target_weight** | **actual_weight** | **variance** |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-01-10T23:15:07.504955 | BATCH_1 | 21.4 | 21.97 | 1.89 |
| 2 | 2026-01-10T22:15:07.504955 | BATCH_2 | 21.4 | 21.99 | 1.72 |
| 3 | 2026-01-10T21:15:07.504955 | BATCH_3 | 21.4 | 21.4 | 0.11 |

---

## 📋 Table: `oee_details_data` (6 rows)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `machine_id` | *character varying.* |
| `loop_id` | *character varying.* |
| `grammage` | *character varying.* |
| `variant` | *character varying.* |
| `availability` | *double precision.* |
| `performance` | *double precision.* |
| `quality` | *double precision.* |
| `oee` | *double precision.* |
| `timestamp` | *timestamp without time zone.* |
| `created_at` | *timestamp without time zone.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **id** | **machine_id** | **loop_id** | **grammage** | **variant** | **availability** | **performance** | **quality** | **oee** | **timestamp** | **created_at** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | M01 | L01 | 100g | Flat Cut | 95.0 | 92.0 | 99.0 | 86.5 | 2026-05-20T08:00:00 | 2026-05-20T14:37:20.420944 |
| 2 | M01 | L01 | 100g | Flat Cut | 94.0 | 91.0 | 98.5 | 84.2 | 2026-05-20T09:00:00 | 2026-05-20T14:37:20.420944 |
| 3 | M01 | L01 | 100g | Flat Cut | 96.0 | 93.0 | 99.2 | 88.6 | 2026-05-20T10:00:00 | 2026-05-20T14:37:20.420944 |

---

## 📋 Table: `operator_certification_levels` (2 rows)
| Column Name | Data Type |
| --- | --- |
| `cert_id` | *integer.* |
| `operator_name` | *character varying.* |
| `certification` | *character varying.* |
| `level` | *integer.* |
| `issued_date` | *date.* |
| `expiry_date` | *date.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **cert_id** | **operator_name** | **certification** | **level** | **issued_date** | **expiry_date** |
| --- | --- | --- | --- | --- | --- |
| 1 | John Smith | RF Feeder Operation | 3 | 2024-01-15 | 2027-01-15 |
| 2 | Jane Doe | Quality Control | 2 | 2024-06-20 | 2026-06-20 |

---

## 📋 Table: `packaging_inventory` (2 rows)
| Column Name | Data Type |
| --- | --- |
| `item_id` | *integer.* |
| `packaging_type` | *character varying.* |
| `quantity_on_hand` | *integer.* |
| `reorder_level` | *integer.* |
| `last_restock_date` | *date.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **item_id** | **packaging_type** | **quantity_on_hand** | **reorder_level** | **last_restock_date** |
| --- | --- | --- | --- | --- |
| 1 | Plastic Bags 50g | 50000 | 10000 | 2025-01-01 |
| 2 | Cardboard Boxes Large | 2000 | 500 | 2024-12-28 |

---

## 📋 Table: `rf_archive_2024` (0 rows - EMPTY)
| Column Name | Data Type |
| --- | --- |
| `archive_id` | *integer.* |
| `archived_date` | *date.* |
| `rf_feeder` | *integer.* |
| `rf_amplitude` | *numeric.* |
| `notes` | *text.* |

> ⚠️ *No rows present in this table.*

---

## 📋 Table: `rf_production_batch_a01` (3 rows)
| Column Name | Data Type |
| --- | --- |
| `batch_id` | *integer.* |
| `timestamp` | *timestamp without time zone.* |
| `rf_feeder` | *integer.* |
| `rf_amplitude` | *numeric.* |
| `rf_weight` | *numeric.* |
| `product_type` | *character varying.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **batch_id** | **timestamp** | **rf_feeder** | **rf_amplitude** | **rf_weight** | **product_type** |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-01-11T00:14:19.523276 | 1 | 50.5 | 3.2 | Candy |
| 2 | 2026-01-11T00:14:19.523276 | 2 | 45.0 | 2.8 | Candy |
| 3 | 2026-01-11T00:14:19.523276 | 3 | 52.3 | 3.5 | Candy |

---

## 📋 Table: `shift_assignments` (3 rows)
| Column Name | Data Type |
| --- | --- |
| `assignment_id` | *integer.* |
| `operator_name` | *character varying.* |
| `shift` | *character varying.* |
| `start_time` | *time without time zone.* |
| `end_time` | *time without time zone.* |
| `line_assigned` | *integer.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **assignment_id** | **operator_name** | **shift** | **start_time** | **end_time** | **line_assigned** |
| --- | --- | --- | --- | --- | --- |
| 1 | John Smith | Morning | 06:00:00 | 14:00:00 | 1 |
| 2 | Jane Doe | Afternoon | 14:00:00 | 22:00:00 | 1 |
| 3 | Bob Johnson | Night | 22:00:00 | 06:00:00 | 2 |

---

## 📋 Table: `sugar_silo_levels` (20 rows)
| Column Name | Data Type |
| --- | --- |
| `reading_id` | *integer.* |
| `timestamp` | *timestamp without time zone.* |
| `silo_number` | *integer.* |
| `level_kg` | *numeric.* |
| `temperature_celsius` | *numeric.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **reading_id** | **timestamp** | **silo_number** | **level_kg** | **temperature_celsius** |
| --- | --- | --- | --- | --- |
| 1 | 2026-01-10T23:15:07.524657 | 3 | 7133.26 | 21.25 |
| 2 | 2026-01-10T22:15:07.524657 | 2 | 5177.32 | 21.63 |
| 3 | 2026-01-10T21:15:07.524657 | 1 | 5015.34 | 19.43 |

---

## 📋 Table: `wastage_records` (5 rows)
| Column Name | Data Type |
| --- | --- |
| `id` | *integer.* |
| `machine_id` | *character varying.* |
| `line_id` | *character varying.* |
| `grammage` | *character varying.* |
| `shift` | *character varying.* |
| `operator_name` | *character varying.* |
| `jta_name` | *character varying.* |
| `shift_incharge_name` | *character varying.* |
| `wastage_kg` | *double precision.* |
| `reason` | *character varying.* |
| `timestamp` | *timestamp without time zone.* |
| `created_at` | *timestamp without time zone.* |

### 🔍 Sample Rows Preview (Up to 3 rows)
| **id** | **machine_id** | **line_id** | **grammage** | **shift** | **operator_name** | **jta_name** | **shift_incharge_name** | **wastage_kg** | **reason** | **timestamp** | **created_at** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | M01 | L01 | 100g | Morning | John Smith | Bob Ross | David Vance | 12.4 | Start-up wastage | 2026-05-20T08:00:00 | 2026-05-20T14:37:20.420944 |
| 2 | M01 | L01 | 100g | Morning | John Smith | Bob Ross | David Vance | 8.6 | Sealing issues | 2026-05-20T09:00:00 | 2026-05-20T14:37:20.420944 |
| 3 | M01 | L01 | 100g | Morning | Jane Doe | Charlie Brown | Emily Watson | 15.2 | Weight variation | 2026-05-20T10:00:00 | 2026-05-20T14:37:20.420944 |

---

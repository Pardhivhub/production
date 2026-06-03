# Anomaly Analysis Report: Recommendations CSV

This report summarizes system configuration and machine learning model recommendation anomalies identified in the recently downloaded file: `Recommendations_2026-05-22_to_2026-05-31.csv`.

## Summary of Findings
- **Total Rows with Maintain Recommendations:** 2228
- **System Configuration Anomalies:** 92 rows where the golden weight setting was set to `0.0`, triggering the fallback recommendation.
- **Extreme Telemetry / ML Model Logic Anomalies:** 31 rows where extreme physical weights (over-weight or under-weight blockages) caused model errors, triggering incorrect fallback `Maintain` recommendations instead of `Decrease` or `Increase` recommendations.

## 1. Extreme Telemetry / ML Model Logic Anomalies (31 Rows)
These represent rows where the feeder weight is significantly larger or smaller than the golden weight setting, but the model fell back to a `Maintain` alert. This indicates that extreme sensor inputs caused errors in the neural network or isotonic regression computations, triggering the hardcoded fallback.

| CSV Row Index | Timestamp | Machine | SKU (Gms) | Variant | Feeder | Feeder Weight | Golden Weight | Weight Ratio (Actual/Golden) | Anomaly Type | Fallback Alert |
|---|---|---|---|---|---|---|---|---|---|---|
| 1133 | 5/26/2026 15:15 | Machine-2 | 11.2 | Ridge Cut | 5 | 0.8 | 3.68 | 0.22 | UNDER-WEIGHT (Should Increase) | Maintain RF 5 amplitude at 36 |
| 2775 | 5/27/2026 4:00 | Machine-4 | 11.2 | Ridge Cut | 5 | 10.5 | 3.28 | 3.2 | OVER-WEIGHT (Should Decrease) | Maintain RF 5 amplitude at 25 |
| 3487 | 5/26/2026 7:30 | Machine-5 | 11.2 | Ridge Cut | 6 | 12.6 | 3.17 | 3.97 | OVER-WEIGHT (Should Decrease) | Maintain RF 6 amplitude at 25 |
| 4299 | 5/26/2026 11:30 | Machine-6 | 11.2 | Ridge Cut | 2 | 11.4 | 3.46 | 3.29 | OVER-WEIGHT (Should Decrease) | Maintain RF 2 amplitude at 31 |
| 4986 | 5/25/2026 8:15 | Machine-7 | 11.2 | Ridge Cut | 4 | 11.6 | 3.44 | 3.37 | OVER-WEIGHT (Should Decrease) | Maintain RF 4 amplitude at 25 |
| 7920 | 5/22/2026 20:45 | Machine-11 | 11.2 | Ridge Cut | 3 | 0.8 | 3.23 | 0.25 | UNDER-WEIGHT (Should Increase) | Maintain RF 3 amplitude at 25 |
| 7994 | 5/23/2026 15:15 | Machine-11 | 11.2 | Ridge Cut | 1 | 11.8 | 3.23 | 3.65 | OVER-WEIGHT (Should Decrease) | Maintain RF 1 amplitude at 33 |
| 8159 | 5/26/2026 7:00 | Machine-11 | 11.2 | Ridge Cut | 5 | 13.2 | 3.23 | 4.09 | OVER-WEIGHT (Should Decrease) | Maintain RF 5 amplitude at 39 |
| 8197 | 5/26/2026 16:15 | Machine-11 | 11.2 | Ridge Cut | 4 | 250.9 | 3.23 | 77.68 | OVER-WEIGHT (Should Decrease) | Maintain RF 4 amplitude at 25 |
| 8221 | 5/26/2026 22:15 | Machine-11 | 11.2 | Ridge Cut | 1 | 10.1 | 3.23 | 3.13 | OVER-WEIGHT (Should Decrease) | Maintain RF 1 amplitude at 40 |
| 8424 | 5/29/2026 1:15 | Machine-11 | 21.4 | Flat Cut | 8 | 1.7 | 5.77 | 0.29 | UNDER-WEIGHT (Should Increase) | Maintain RF 8 amplitude at 56 |
| 8429 | 5/29/2026 3:00 | Machine-11 | 21.4 | Flat Cut | 8 | 1.9 | 5.77 | 0.33 | UNDER-WEIGHT (Should Increase) | Maintain RF 8 amplitude at 56 |
| 8726 | 5/22/2026 22:30 | Machine-12 | 11.2 | Ridge Cut | 2 | 1.2 | 3.97 | 0.3 | UNDER-WEIGHT (Should Increase) | Maintain RF 2 amplitude at 80 |
| 9016 | 5/26/2026 21:45 | Machine-12 | 11.2 | Ridge Cut | 1 | 0.9 | 3.97 | 0.23 | UNDER-WEIGHT (Should Increase) | Maintain RF 1 amplitude at 80 |
| 9862 | 5/27/2026 9:30 | Machine-13 | 11.2 | Ridge Cut | 1 | 0.7 | 3.72 | 0.19 | UNDER-WEIGHT (Should Increase) | Maintain RF 1 amplitude at 25 |
| 9927 | 5/28/2026 1:30 | Machine-13 | 21.4 | Flat Cut | 4 | 2.0 | 6.31 | 0.32 | UNDER-WEIGHT (Should Increase) | Maintain RF 4 amplitude at 80 |
| 10325 | 5/22/2026 23:45 | Machine-14 | 11.2 | Ridge Cut | 2 | 11.3 | 3.71 | 3.05 | OVER-WEIGHT (Should Decrease) | Maintain RF 2 amplitude at 36 |
| 10385 | 5/23/2026 14:45 | Machine-14 | 11.2 | Ridge Cut | 1 | 1.1 | 3.71 | 0.3 | UNDER-WEIGHT (Should Increase) | Maintain RF 1 amplitude at 74 |
| 10627 | 5/27/2026 2:00 | Machine-14 | 11.2 | Ridge Cut | 8 | 18.9 | 3.71 | 5.09 | OVER-WEIGHT (Should Decrease) | Maintain RF 8 amplitude at 25 |
| 11150 | 5/23/2026 6:45 | Machine-15 | 11.2 | Ridge Cut | 2 | 13.9 | 3.28 | 4.24 | OVER-WEIGHT (Should Decrease) | Maintain RF 2 amplitude at 44 |
| 11152 | 5/23/2026 7:30 | Machine-15 | 11.2 | Ridge Cut | 5 | 11.1 | 3.28 | 3.38 | OVER-WEIGHT (Should Decrease) | Maintain RF 5 amplitude at 25 |
| 12172 | 5/26/2026 14:45 | Machine-16 | 11.2 | Ridge Cut | 1 | 1.0 | 3.44 | 0.29 | UNDER-WEIGHT (Should Increase) | Maintain RF 1 amplitude at 36 |
| 12183 | 5/26/2026 17:15 | Machine-16 | 11.2 | Ridge Cut | 4 | 0.1 | 3.44 | 0.03 | UNDER-WEIGHT (Should Increase) | Maintain RF 4 amplitude at 25 |
| 12250 | 5/27/2026 10:00 | Machine-16 | 11.2 | Ridge Cut | 3 | 48.1 | 3.44 | 13.98 | OVER-WEIGHT (Should Decrease) | Maintain RF 3 amplitude at 25 |
| 12285 | 5/27/2026 18:30 | Machine-16 | 21.4 | Flat Cut | 2 | 26.2 | 5.2 | 5.04 | OVER-WEIGHT (Should Decrease) | Maintain RF 2 amplitude at 36 |
| 12873 | 5/25/2026 15:00 | Machine-17 | 11.2 | Ridge Cut | 5 | 14.5 | 3.8 | 3.82 | OVER-WEIGHT (Should Decrease) | Maintain RF 5 amplitude at 57 |
| 13677 | 5/26/2026 18:45 | Machine-18 | 11.2 | Ridge Cut | 8 | 12.1 | 3.97 | 3.05 | OVER-WEIGHT (Should Decrease) | Maintain RF 8 amplitude at 25 |
| 13731 | 5/27/2026 8:15 | Machine-18 | 11.2 | Ridge Cut | 3 | 13.8 | 3.97 | 3.48 | OVER-WEIGHT (Should Decrease) | Maintain RF 3 amplitude at 25 |
| 13920 | 5/29/2026 9:45 | Machine-18 | 21.4 | Flat Cut | 1 | 1.8 | 5.5 | 0.33 | UNDER-WEIGHT (Should Increase) | Maintain RF 1 amplitude at 27 |
| 14324 | 5/26/2026 8:00 | Machine-19 | 11.2 | Ridge Cut | 5 | 11.3 | 3.5 | 3.23 | OVER-WEIGHT (Should Decrease) | Maintain RF 5 amplitude at 25 |
| 14708 | 5/30/2026 10:00 | Machine-19 | 21.4 | Flat Cut | 2 | 1.7 | 5.43 | 0.31 | UNDER-WEIGHT (Should Increase) | Maintain RF 2 amplitude at 43 |

## 2. System Configuration Anomalies (92 Rows)
These represent rows where the golden weight is set to `0.0` or `0` for production runs. This configuration error causes the difference calculation to fail, resulting in fallback `Maintain` recommendations.

| CSV Row Index | Timestamp | Machine | SKU (Gms) | Variant | Feeder | Feeder Weight | Golden Weight | Fallback Alert |
|---|---|---|---|---|---|---|---|---|
| 42 | 5/22/2026 16:15 | Machine-1 | 82.0 | - | 6 | 13.1 | 0.0 | Maintain RF 6 amplitude at 80 |
| 142 | 5/23/2026 16:45 | Machine-1 | 82.0 | - | 3 | 17.5 | 0.0 | Maintain RF 3 amplitude at 25 |
| 144 | 5/23/2026 17:15 | Machine-1 | 82.0 | - | 3 | 17.2 | 0.0 | Maintain RF 3 amplitude at 25 |
| 150 | 5/23/2026 18:45 | Machine-1 | 110.0 | - | 7 | 1.1 | 0.0 | Maintain RF 7 amplitude at 80 |
| 153 | 5/23/2026 19:15 | Machine-1 | 82.0 | - | 2 | 13.6 | 0.0 | Maintain RF 2 amplitude at 25 |
| 155 | 5/23/2026 19:45 | Machine-1 | 82.0 | - | 2 | 20.2 | 0.0 | Maintain RF 2 amplitude at 25 |
| 156 | 5/23/2026 20:00 | Machine-1 | 82.0 | - | 2 | 19.8 | 0.0 | Maintain RF 2 amplitude at 25 |
| 157 | 5/23/2026 20:15 | Machine-1 | 82.0 | - | 2 | 19.1 | 0.0 | Maintain RF 2 amplitude at 25 |
| 158 | 5/23/2026 20:30 | Machine-1 | 82.0 | - | 2 | 20.9 | 0.0 | Maintain RF 2 amplitude at 25 |
| 159 | 5/23/2026 20:45 | Machine-1 | 82.0 | - | 2 | 22.4 | 0.0 | Maintain RF 2 amplitude at 25 |
| 160 | 5/23/2026 21:00 | Machine-1 | 82.0 | - | 2 | 20.8 | 0.0 | Maintain RF 2 amplitude at 25 |
| 162 | 5/23/2026 21:30 | Machine-1 | 82.0 | - | 2 | 21.0 | 0.0 | Maintain RF 2 amplitude at 25 |
| 163 | 5/23/2026 21:45 | Machine-1 | 82.0 | - | 2 | 22.0 | 0.0 | Maintain RF 2 amplitude at 25 |
| 164 | 5/23/2026 22:00 | Machine-1 | 82.0 | - | 2 | 18.7 | 0.0 | Maintain RF 2 amplitude at 25 |
| 170 | 5/23/2026 23:30 | Machine-1 | 82.0 | - | 7 | 5.8 | 0.0 | Maintain RF 7 amplitude at 80 |
| 171 | 5/23/2026 23:45 | Machine-1 | 82.0 | - | 7 | 7.4 | 0.0 | Maintain RF 7 amplitude at 80 |
| 238 | 5/25/2026 15:30 | Machine-1 | 82.0 | - | 2 | 13.4 | 0.0 | Maintain RF 2 amplitude at 25 |
| 286 | 5/26/2026 3:00 | Machine-1 | 82.0 | - | 9 | 14.7 | 0.0 | Maintain RF 9 amplitude at 48 |
| 291 | 5/26/2026 4:15 | Machine-1 | 82.0 | - | 1 | 9.0 | 0.0 | Maintain RF 1 amplitude at 80 |
| 292 | 5/26/2026 4:30 | Machine-1 | 82.0 | - | 1 | 9.0 | 0.0 | Maintain RF 1 amplitude at 80 |
| 4770 | 5/31/2026 11:30 | Machine-6 | 85.0 | Flat Cut | 3 | 13.6 | 0.0 | Maintain RF 3 amplitude at 53 | IF/DF decreased by 10 (EGA increasing -0.05%→-0.01%). |
| 7903 | 5/22/2026 16:45 | Machine-11 | 82.0 | - | 5 | 16.1 | 0.0 | Maintain RF 5 amplitude at 25 |
| 7904 | 5/22/2026 17:00 | Machine-11 | 82.0 | - | 2 | 17.1 | 0.0 | Maintain RF 2 amplitude at 25 |
| 7906 | 5/22/2026 17:30 | Machine-11 | 82.0 | - | 2 | 15.2 | 0.0 | Maintain RF 2 amplitude at 25 |
| 7907 | 5/22/2026 17:45 | Machine-11 | 82.0 | - | 2 | 17.3 | 0.0 | Maintain RF 2 amplitude at 25 |
| 7908 | 5/22/2026 18:00 | Machine-11 | 82.0 | - | 8 | 18.4 | 0.0 | Maintain RF 8 amplitude at 25 |
| 8004 | 5/23/2026 17:30 | Machine-11 | 82.0 | - | 2 | 29.0 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8005 | 5/23/2026 17:45 | Machine-11 | 82.0 | - | 8 | 27.4 | 0.0 | Maintain RF 8 amplitude at 25 |
| 8007 | 5/23/2026 18:15 | Machine-11 | 82.0 | - | 2 | 31.1 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8008 | 5/23/2026 18:30 | Machine-11 | 82.0 | - | 2 | 31.6 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8009 | 5/23/2026 18:45 | Machine-11 | 82.0 | - | 2 | 31.9 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8010 | 5/23/2026 19:00 | Machine-11 | 82.0 | - | 2 | 33.5 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8011 | 5/23/2026 19:15 | Machine-11 | 82.0 | - | 2 | 32.4 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8012 | 5/23/2026 19:30 | Machine-11 | 82.0 | - | 2 | 48.2 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8013 | 5/23/2026 19:45 | Machine-11 | 82.0 | - | 2 | 37.4 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8014 | 5/23/2026 20:00 | Machine-11 | 82.0 | - | 2 | 37.2 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8015 | 5/23/2026 20:15 | Machine-11 | 82.0 | - | 2 | 30.9 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8016 | 5/23/2026 20:30 | Machine-11 | 82.0 | - | 2 | 31.6 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8017 | 5/23/2026 20:45 | Machine-11 | 82.0 | - | 2 | 35.8 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8018 | 5/23/2026 21:00 | Machine-11 | 82.0 | - | 9 | 31.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 8019 | 5/23/2026 21:15 | Machine-11 | 82.0 | - | 2 | 29.2 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8020 | 5/23/2026 21:30 | Machine-11 | 82.0 | - | 2 | 29.5 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8021 | 5/23/2026 21:45 | Machine-11 | 82.0 | - | 2 | 30.9 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8022 | 5/23/2026 22:00 | Machine-11 | 82.0 | - | 2 | 28.8 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8025 | 5/23/2026 22:45 | Machine-11 | 82.0 | - | 2 | 27.3 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8026 | 5/23/2026 23:00 | Machine-11 | 82.0 | - | 2 | 19.6 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8027 | 5/23/2026 23:15 | Machine-11 | 82.0 | - | 2 | 20.6 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8029 | 5/23/2026 23:45 | Machine-11 | 82.0 | - | 2 | 38.5 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8030 | 5/24/2026 0:00 | Machine-11 | 82.0 | - | 2 | 38.8 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8031 | 5/24/2026 0:15 | Machine-11 | 82.0 | - | 2 | 30.4 | 0.0 | Maintain RF 2 amplitude at 25 |
| 8044 | 5/24/2026 3:30 | Machine-11 | 82.0 | - | 7 | 18.4 | 0.0 | Maintain RF 7 amplitude at 25 |
| 8045 | 5/24/2026 3:45 | Machine-11 | 82.0 | - | 9 | 18.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 8052 | 5/24/2026 5:30 | Machine-11 | 82.0 | - | 6 | 7.7 | 0.0 | Maintain RF 6 amplitude at 82 |
| 8053 | 5/24/2026 5:45 | Machine-11 | 82.0 | - | 6 | 2.1 | 0.0 | Maintain RF 6 amplitude at 82 |
| 9503 | 5/22/2026 17:30 | Machine-13 | 82.0 | - | 8 | 23.2 | 0.0 | Maintain RF 8 amplitude at 25 |
| 9504 | 5/22/2026 17:45 | Machine-13 | 82.0 | - | 9 | 23.1 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9505 | 5/22/2026 18:00 | Machine-13 | 82.0 | - | 9 | 19.7 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9506 | 5/22/2026 18:15 | Machine-13 | 82.0 | - | 9 | 19.9 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9507 | 5/22/2026 18:30 | Machine-13 | 82.0 | - | 9 | 19.1 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9508 | 5/22/2026 18:45 | Machine-13 | 82.0 | - | 9 | 19.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9509 | 5/22/2026 19:00 | Machine-13 | 82.0 | - | 9 | 19.7 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9510 | 5/22/2026 19:15 | Machine-13 | 82.0 | - | 9 | 18.9 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9519 | 5/22/2026 21:30 | Machine-13 | 82.0 | - | 9 | 19.5 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9520 | 5/22/2026 21:45 | Machine-13 | 82.0 | - | 9 | 20.8 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9598 | 5/23/2026 17:00 | Machine-13 | 82.0 | - | 9 | 18.9 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9599 | 5/23/2026 17:15 | Machine-13 | 82.0 | - | 9 | 21.9 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9600 | 5/23/2026 17:30 | Machine-13 | 82.0 | - | 9 | 21.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9601 | 5/23/2026 17:45 | Machine-13 | 82.0 | - | 9 | 19.0 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9602 | 5/23/2026 18:00 | Machine-13 | 82.0 | - | 9 | 19.5 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9603 | 5/23/2026 18:15 | Machine-13 | 82.0 | - | 9 | 19.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9604 | 5/23/2026 18:30 | Machine-13 | 82.0 | - | 9 | 19.6 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9605 | 5/23/2026 18:45 | Machine-13 | 82.0 | - | 9 | 21.6 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9606 | 5/23/2026 19:00 | Machine-13 | 82.0 | - | 9 | 22.4 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9613 | 5/23/2026 20:45 | Machine-13 | 82.0 | - | 9 | 22.5 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9614 | 5/23/2026 21:00 | Machine-13 | 82.0 | - | 9 | 22.7 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9615 | 5/23/2026 21:15 | Machine-13 | 82.0 | - | 9 | 21.8 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9616 | 5/23/2026 21:30 | Machine-13 | 82.0 | - | 9 | 21.7 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9617 | 5/23/2026 21:45 | Machine-13 | 82.0 | - | 9 | 20.8 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9618 | 5/23/2026 22:00 | Machine-13 | 82.0 | - | 9 | 21.5 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9619 | 5/23/2026 22:15 | Machine-13 | 82.0 | - | 9 | 23.0 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9620 | 5/23/2026 22:30 | Machine-13 | 82.0 | - | 9 | 22.1 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9621 | 5/23/2026 22:45 | Machine-13 | 82.0 | - | 9 | 20.2 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9622 | 5/23/2026 23:00 | Machine-13 | 82.0 | - | 9 | 27.3 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9623 | 5/23/2026 23:15 | Machine-13 | 82.0 | - | 9 | 22.0 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9625 | 5/23/2026 23:45 | Machine-13 | 82.0 | - | 9 | 19.7 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9626 | 5/24/2026 0:00 | Machine-13 | 82.0 | - | 9 | 27.6 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9627 | 5/24/2026 0:15 | Machine-13 | 82.0 | - | 9 | 26.6 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9628 | 5/24/2026 0:30 | Machine-13 | 82.0 | - | 9 | 27.0 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9629 | 5/24/2026 0:45 | Machine-13 | 82.0 | - | 9 | 26.0 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9630 | 5/24/2026 1:00 | Machine-13 | 82.0 | - | 9 | 26.6 | 0.0 | Maintain RF 9 amplitude at 25 |
| 9638 | 5/24/2026 3:00 | Machine-13 | 82.0 | - | 4 | 6.6 | 0.0 | Maintain RF 4 amplitude at 80 |
| 11014 | 5/31/2026 5:00 | Machine-14 | 43.0 | Flat Cut | 9 | 7.1 | 0.0 | Maintain RF 9 amplitude at 48 |

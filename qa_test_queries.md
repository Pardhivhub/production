# Industrial IoT Database - QA Test Suite

This document contains a comprehensive list of test questions designed to rigorously validate the Text-to-SQL AI engine. 

## 1. Core Logic & Math Calculations
*Tests division safety (NULLIF) and complex percentages.*
- "What is the quality percentage for all machines?"
- "What is the quality percentage for Machine-10 on 2025-05-28?"
- "Which machine had the worst quality percentage on 2025-06-03?"
- "Which machine had the highest rate of failed bags per minute of downtime on 2025-05-28?"
- "What was the ratio of empty bags to good bags for Machine 5 on 2025-06-03?"

## 2. Advanced Grouping (Custom Entities)
*Tests if the AI correctly groups by custom metrics rather than always defaulting to `machine_id`.*
- "Which grammage produced the most good bags on 2025-06-03?"
- "What is the average EGA percent for each grammage size?"
- "For the Flat Cut variant on 2025-05-28, which grammage size had the lowest average EGA percent?"
- "Compare the average EGA for grammage 20 and grammage 50 on 2025-05-28."

## 3. "Loops" and "Variants" Routing
*Tests if the AI knows that variants and loop_names belong to production tables (`ega_details_data`, `oee_details_data`), NOT the `machines` table.*
- "Which loop had the lowest total downtime on 2025-05-29?"
- "Compare the total failed bags for loop 1 and loop 2 on 2025-05-28."
- "What was the average EGA percent for loop_1 on 2025-06-01?"
- "Which loop had the best quality percentage on 2025-05-28?"
- "For the Ridge Cut variant on 2025-05-30, which grammage size had the highest average EGA percent?"
- "Which machine produced the most failed bags while running the Ridge Cut variant on 2025-06-02?"

## 4. Multi-Machine Comparisons
*Tests if the AI correctly generates `IN (...)` filters for comparison.*
- "Compare the downtime and failed bags for Machine 6 and 7 on 2025-05-28."
- "Compare the quality percentage for Machine 1 and Machine 2 on 2025-06-02."

## 5. Plant & Line Hierarchy (3-Table JOINs)
*Tests the JOIN paths between `wastage_records`, `gmiiot_lines`, and `gmiiot_plants`.*
- "Which line in Plant 1 had the lowest wastage on 2025-05-28?"
- "Compare the total wastage between Plant 1 and Plant 2 on 2025-05-30."
- "Which plant had the highest total downtime on 2025-06-02?"
- "Which line in the West Dustin plant had the highest average EGA percent on 2025-06-03?"
- "Compare the total wastage kg between Line 1 and Line 2 in Plant 1 on 2025-05-28."

## 6. Advanced Data Types & Functions
*Tests JSON array unnesting and date ranges.*
- "What was the average production speed (BPM) for Machine 12 on 2025-06-03?"
- "Which machine had the highest average production speed on 2025-05-28?"
- "What was the total wastage for Plant 1 for the entire month of May 2025?"
- "Compare the total good bags produced between 2025-05-28 and 2025-06-02 for Machine 10."

## 7. Trick Columns & Shifts
*Tests subtle column naming differences and grouping by shift.*
- "What was the total weight in kg of failed bags for Machine 6 on 2025-06-03?" (Testing `failed_bags_kg` vs `failed_bags`)
- "Which machine had the most jaw jam errors by count (not weight) on 2025-05-29?"
- "Compare the total wastage between the morning and night shifts on 2025-05-28."
- "Which shift had the highest average EGA percent on 2025-06-02?"

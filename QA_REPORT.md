# QA Test Suite Results


## 1. Core Logic & Math Calculations
### Q: What is the quality percentage for all machines?
**Answer:**
Here's a concise explanation of the query results:

The quality percentage for all machines ranges from 92.25% to 99.17%. Machine-3 leads at 99.17%, followed by Machine-4 at 99.11%.

Would you like me to drill down into a specific machine?
---
### Q: What is the quality percentage for Machine-10 on 2025-05-28?
**Answer:**
Here's a concise explanation of the query results:

The quality percentage for Machine-10 on 2025-05-28 is 99.70%. This means that out of all bags produced by this machine, about 99.70% were good bags.

Would you like me to drill down into a specific machine?
---
### Q: Which machine had the worst quality percentage on 2025-06-03?
**Answer:**
Here's a concise explanation of the results:

The Sealer-16 machine had the worst quality percentage on 2025-06-03, with a value of 149.82%. This means it produced significantly fewer good bags than expected.

Would you like me to drill down into this specific machine's performance?
---
### Q: Which machine had the highest rate of failed bags per minute of downtime on 2025-05-28?
**Answer:**
Error parsing SSE payload
---
### Q: What was the ratio of empty bags to good bags for Machine 5 on 2025-06-03?
**Answer:**
Error parsing SSE payload
---

## 2. Advanced Grouping (Custom Entities)
### Q: Which grammage produced the most good bags on 2025-06-03?
**Answer:**
Here's a concise explanation of the query results:

The data shows that on 2025-06-03, Machine 14 produced the most good bags with 22 units. 

Would you like me to drill down into this machine's production performance?
---
### Q: What is the average EGA percent for each grammage size?
**Answer:**
Here's a concise explanation of the query results:

The average EGA percent for each grammage size ranges from -754.92 to 0.98, with an average of 0.47%. The top three grammages are 21.0g, 10.5g, and 43.0g, with averages of 0.98%, 0.68%, and 0.14%, respectively.

Would you like me to drill down into a specific machine?
---
### Q: For the Flat Cut variant on 2025-05-28, which grammage size had the lowest average EGA percent?
**Answer:**
Error parsing SSE payload
---
### Q: Compare the average EGA for grammage 20 and grammage 50 on 2025-05-28.
**Answer:**
Error parsing SSE payload
---

## 3. "Loops" and "Variants" Routing
### Q: Which loop had the lowest total downtime on 2025-05-29?
**Answer:**
Error parsing SSE payload
---
### Q: Compare the total failed bags for loop 1 and loop 2 on 2025-05-28.
**Answer:**
Error parsing SSE payload
---
### Q: What was the average EGA percent for loop_1 on 2025-06-01?
**Answer:**
Here's a possible response:

The data shows an average EGA percent of 0.00% for loop_1 on 2025-06-01. Unfortunately, no good bags were recorded for this machine on this day.

Would you like me to drill down into the downtime or wastage for this specific machine?
---
### Q: Which loop had the best quality percentage on 2025-05-28?
**Answer:**
Here's a concise explanation of the query results for the factory manager:

On 2025-05-28, "Filler-2" had the best quality percentage at 100.0%, followed by "Filler-18" at 99.97%. The lowest quality was recorded by "Robot-12" with 0%.

Would you like me to drill down into a specific machine's performance?
---
### Q: For the Ridge Cut variant on 2025-05-30, which grammage size had the highest average EGA percent?
**Answer:**
Error parsing SSE payload
---
### Q: Which machine produced the most failed bags while running the Ridge Cut variant on 2025-06-02?
**Answer:**
No machine produced any failed bags on 2025-06-02 while running the Ridge Cut variant.

Possible reasons for this result could be:
* Date mismatch: Double-check that the start time is correct.
* Variant name mismatch: Verify that 'Ridge Cut' is the exact variant used.
* No data for that period: Check if there's any data available for 2025-06-02.

Would you like me to check available dates, variants, or machines?

💡 **Suggestion**: No results found in `flavours`. You might want to check: `wastage_reasons`, `conversation_turns`, `semantic_query_cache`
---

## 4. Multi-Machine Comparisons
### Q: Compare the downtime and failed bags for Machine 6 and 7 on 2025-05-28.
**Answer:**
Here's a concise explanation of the query results:

Machine 6 had 460.7 minutes of downtime and 942 failed bags, while Machine 7 had 313.6 minutes of downtime and 1370 failed bags. 

Would you like me to drill down into specific machines' performance on that day?
---
### Q: Compare the quality percentage for Machine 1 and Machine 2 on 2025-06-02.
**Answer:**
The data shows that on 2025-06-02, Machine 1 had a quality percentage of 98.91% and Machine 2 had a quality percentage of 92.88%.

Would you like me to compare this across shifts?
---

## 5. Plant & Line Hierarchy (3-Table JOINs)
### Q: Which line in Plant 1 had the lowest wastage on 2025-05-28?
**Answer:**
No wastage was recorded on 2025-05-28 for any line in Plant 1.

Possible reasons include:
- Date format mismatch
- Variant name mismatch
- No data exists for that production period

Would you like me to check available dates or variants?

💡 **Suggestion**: No results found in `wastage_reasons`. You might want to check: `flavours`, `conversation_turns`, `semantic_query_cache`
---
### Q: Compare the total wastage between Plant 1 and Plant 2 on 2025-05-30.
**Answer:**
Plant 1 and Plant 2 had zero wastage on May 30, 2025. 

Would you like me to investigate if this was an anomaly or a normal production day?
---
### Q: Which plant had the highest total downtime on 2025-06-02?
**Answer:**
Error parsing SSE payload
---
### Q: Which line in the West Dustin plant had the highest average EGA percent on 2025-06-03?
**Answer:**
HTTP/Timeout Error: timed out
---
### Q: Compare the total wastage kg between Line 1 and Line 2 in Plant 1 on 2025-05-28.
**Answer:**
The data shows no wastage recorded for Line 1 and Line 2 on 2025-05-28. 

Would you like me to investigate why there's no data available?
---

## 6. Advanced Data Types & Functions
### Q: What was the average production speed (BPM) for Machine 12 on 2025-06-03?
**Answer:**
The average production speed for Machine 12 on June 3, 2025, was 47.49 BPM.

Would you like me to compare this across shifts?
---
### Q: Which machine had the highest average production speed on 2025-05-28?
**Answer:**
HTTP/Timeout Error: timed out
---
### Q: What was the total wastage for Plant 1 for the entire month of May 2025?
**Answer:**
The total wastage for Plant 1 in May 2025 was 0.0 kg. This means there was no excess give away (EGA) during this period, indicating that all products were packed to target weight.

Would you like me to review the wastage records for a specific machine?

💡 **Suggestion**: No results found in `wastage_reasons`. You might want to check: `flavours`, `conversation_turns`, `semantic_query_cache`
---
### Q: Compare the total good bags produced between 2025-05-28 and 2025-06-02 for Machine 10.
**Answer:**
Here's a concise explanation of the results:

The total good bags produced between 2025-05-28 and 2025-06-02 for Machine 10 is 0. 

Would you like me to compare this across shifts?
---

## 7. Trick Columns & Shifts
### Q: What was the total weight in kg of failed bags for Machine 6 on 2025-06-03?
**Answer:**
HTTP/Timeout Error: timed out
---
### Q: Which machine had the most jaw jam errors by count (not weight) on 2025-05-29?
**Answer:**
Error parsing SSE payload
---
### Q: Compare the total wastage between the morning and night shifts on 2025-05-28.
**Answer:**
Error parsing SSE payload
---
### Q: Which shift had the highest average EGA percent on 2025-06-02?
*Status: Pending...*
---

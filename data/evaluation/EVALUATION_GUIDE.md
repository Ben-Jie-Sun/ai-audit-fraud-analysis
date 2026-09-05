# Fixed evaluation workbook suite

These 21 XLSX files are committed so a judge/tester can exercise the project without first running a generator. Valid benchmark files include evaluation-only labels (`synthetic_anomaly`, `anomaly_type`); the inference pipeline ignores those columns.

| File | Purpose | Expected use |
|---|---|---|
| 01_clean_small.xlsx | Small clean ledger | False-positive sanity check |
| 02_extreme_amount.xlsx | Large amount spikes | Strong amount anomaly test |
| 03_moderate_amount.xlsx | Subtler amount changes | Harder amount test |
| 04_duplicate_payment.xlsx | Repeated payment pairs | Duplicate-pattern test |
| 05_split_payment.xlsx | Same-day payments split below approval threshold | Threshold-evasion pattern |
| 06_vendor_burst.xlsx | Repeated same-vendor activity in a short window | Burst-pattern test |
| 07_category_shift.xlsx | Employee shifts to atypical category late in timeline | Past-profile deviation |
| 08_location_shift.xlsx | Employee shifts location with spending change | Past-location deviation challenge |
| 09_rounded_repeat.xlsx | Repeated 49,999-like values | Repeated rounded-value pattern |
| 10_mixed_subtle.xlsx | Moderate amount + category + location shifts | Mixed subtle challenge |
| 11_mixed_operational.xlsx | Duplicate + split + burst + rounded repeat | Operational fraud-pattern mix |
| 12_mixed_all_patterns.xlsx | All supported injected patterns | Broad benchmark |
| 13_clean_medium.xlsx | 1,000 clean rows | Medium clean sanity check |
| 14_mixed_medium.xlsx | 1,000 rows, mixed anomalies | General benchmark |
| 15_high_anomaly_batch.xlsx | High anomaly density | Batch review behaviour |
| 16_large_clean.xlsx | 3,000 clean rows | Larger false-positive/scalability check |
| 17_large_mixed.xlsx | 3,000 mixed rows | Larger benchmark/scalability check |
| 18_missing_optional_fields.xlsx | Valid ledger without optional fields | Schema flexibility test |
| 19_invalid_missing_required.xlsx | Missing vendor/category | Expected friendly validation failure |
| 20_invalid_amount.xlsx | Non-numeric amount | Expected friendly validation failure |
| 21_systemic_high_anomaly_60.xlsx | 60% injected strong fraud-like patterns | Worst-case systemic review / majority-abnormal test |

The suite is a reproducible benchmark, not evidence of real-world fraud accuracy. Synthetic patterns are used to measure whether known injected behaviours are detected.


## Important majority-anomaly limitation

Clustering and Isolation Forest are **relative** methods: they learn what is typical inside the uploaded population. If abnormal behaviour becomes the majority, some abnormal behaviour can start to look statistically normal. The audit engine therefore does not rely on those signals alone. It also uses explicit audit-pattern checks and an external `APPROVAL_THRESHOLD` control. The 60% systemic workbook is included to make this limitation visible rather than hide it.

### 22_flexible_schema_typos.xlsx
Tests automatic schema mapping with aliases and spelling mistakes such as `Merchent`, `Expense Catagory`, and `Locatoin`. The canonical audit schema should be recovered before analysis.

### 23_missing_vendor_category_location.xlsx
Tests optional-field-aware analysis. Vendor, category, and location are deliberately absent. The ledger should still run, while vendor/category/location-dependent signals are reported as skipped rather than fabricated.

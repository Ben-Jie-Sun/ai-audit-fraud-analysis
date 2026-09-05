# Transaction anomaly model notes

## What is a cluster distance?
Transactions are converted to standardized behavioural features and assigned to a K-Means cluster. `cluster_distance` is the Euclidean distance from the transaction to the centre of its assigned cluster. Larger values mean the row is less typical of that cluster. It is not a probability of fraud.

## What is an isolation score?
Isolation Forest gives larger normality scores to ordinary observations. The application inverts that score, so a larger `isolation_score` means the transaction is easier to isolate from the rest of the dataset. It is not a probability of fraud.

## Why combine multiple signals?
A single model can overreact to unusual-but-legitimate data. The engine therefore combines model signals with auditable patterns such as duplicates, split payments, bursts, historical category/location changes, repeated rounded values, and amount deviations.

## Ground-truth leakage control
The benchmark columns `synthetic_anomaly`, `anomaly_type`, `ground_truth`, `expected_anomaly`, and `expected_pattern` are explicitly removed before feature engineering. Tests verify that changing these labels does not change features or predictions.

## Known limitation
The model learns primarily from the uploaded ledger. Coordinated behaviour that becomes common inside the same batch can be harder to classify as unusual. Past-only employee category/location shares partially address this by using only earlier-dated transactions for profile-shift features. A production system would usually maintain a separate historical reference store and versioned model/profile state.

## Synthetic benchmark terminology

Synthetic benchmark labels are never model inputs. They exist only to evaluate predictions after inference.

- **True Positive (TP):** injected anomaly correctly flagged.
- **False Positive (FP):** benchmark-normal transaction incorrectly flagged.
- **False Negative (FN):** injected anomaly missed by the detector.
- **True Negative (TN):** benchmark-normal transaction correctly left unflagged.
- **Precision:** TP / (TP + FP).
- **Recall:** TP / (TP + FN).
- **F1:** harmonic mean of precision and recall.

## Majority-abnormal populations

K-Means and Isolation Forest are relative to the uploaded population. If abnormal behaviour dominates the ledger, some abnormal rows can begin to define the learned baseline. The hybrid detector therefore also uses explicit audit patterns and the external `APPROVAL_THRESHOLD` control. A batch with >=50% detected anomalies is labelled `SYSTEMIC REVIEW REQUIRED` and should not be auto-cleared.

## Phase 3 risk layer

The transaction risk score is separate from `cluster_distance`,
`isolation_score`, and `is_anomaly`. It is an explainable weighted control score
used to prioritize review. It is capped at 100 and must not be presented as a
calibrated fraud probability.

Current risk bands:
- 0-24 LOW
- 25-49 MEDIUM
- 50-74 HIGH
- 75-100 CRITICAL

Reviewer routing is deterministic and auditable. Benchmark-only fields such as
`synthetic_anomaly` and `anomaly_type` do not contribute to the risk score.

## Signal availability and schema mapping

The fraud engine does not assume every ledger contains merchant/vendor, category, location, department, or payment-method fields. External headers are mapped conservatively into a canonical internal schema. Optional-data-dependent signals are disabled when their source field is unavailable. This prevents a missing merchant column from being converted into an artificial "Unknown Vendor" group that could create false vendor bursts or split-payment signals.

`schema_mapping` and `data_coverage` are diagnostic metadata. They are not model features.

## Phase 5 input-coverage policy

The transaction ML path now has an explicit input contract:
- **Minimum required:** transaction ID, date, amount, and employee ID or employee name.
- **Recommended context:** vendor, category, location, department, manager name, payment method.
- **Optional:** description and unrelated extra columns.

The minimum contract is enforced before model fitting. Recommended fields are signal-aware: if a field is absent, only dependent checks are disabled. The API/UI expose a recommended-context coverage ratio and schema tier (`MINIMUM CONTEXT`, `MEDIUM CONTEXT`, `FULL CONTEXT`). This ratio describes input coverage, not model confidence.

Header aliases and small spelling mistakes are mapped conservatively to canonical fields. Weak/ambiguous guesses remain unmapped. Judge-facing examples live under `data/schema_examples/`.

## Phase 6 integration note

Detection and operational review are separate layers. Transaction anomaly evidence and document findings are produced by different engines, but both now feed the same review-priority vocabulary:

`LOW -> MEDIUM -> HIGH -> CRITICAL`

The shared review layer is not a second fraud model. It is deterministic routing over already-computed evidence. Its score/band should always be described as **review priority**, never as fraud probability.

Standalone documents have no employee manager field, so MEDIUM document cases route to `Accounts Payable / Line Manager`; HIGH and CRITICAL use the same Finance/Internal Audit and Senior Audit/Fraud Investigation escalation used by transactions.


## Phase 7 assistant boundary

The audit assistant is not another fraud model. It is downstream of the existing transaction/document pipelines. Its sequence is:

`computed audit result -> deterministic retrieval/aggregation -> bounded fact packet -> answer`

An optional LLM can rewrite the grounded answer for readability, but it receives only the retrieved facts selected by the application. The assistant does not refit K-Means/Isolation Forest, change risk scores, infer fraud, or use synthetic benchmark labels as evidence. If a question cannot be mapped to cached evidence, the correct response is an explicit unsupported/insufficient-evidence message rather than a guess.

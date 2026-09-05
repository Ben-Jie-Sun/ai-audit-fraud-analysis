# Project architecture history (internal development note)

This note exists so the final README and demo remain aligned with the actual code.

## 1. Initial document-audit MVP
The project began as a single-document audit assistant:

`document -> parser/sanitizer -> ExtractedInvoice -> deterministic rules -> statistical amount check -> transparent risk score -> LLM/template explanation`

The LLM is downstream of the audit logic and does not decide fraud or risk. Prompt-like text found in untrusted documents is surfaced as an audit finding.

## 2. Transaction-ledger path
For the ATH problem **Fraud Pattern Clustering in Transactions**, a separate batch path was added:

`CSV/XLSX ledger -> validation/normalization -> behavioural features -> clustering + anomaly screening -> review decision -> dashboard/report`

The document path remains an additional capability; transaction intelligence is the hackathon core.

## 3. Phase 2B: hybrid fraud-pattern screening
The transaction engine now combines:
- K-Means behavioural clustering,
- Isolation Forest unusualness scoring,
- cluster-distance deviation,
- past-only employee category/location profiles,
- explicit auditable signals for duplicate payments, split payments, vendor bursts, employee bursts, repeated rounded values, category/location shifts, and amount deviations.

`cluster_distance` and `isolation_score` are ranking/evidence signals, **not fraud probabilities**.

## 4. Benchmark integrity
Generated and curated benchmark files can contain `synthetic_anomaly` and `anomaly_type` columns. These are evaluation-only labels. They are explicitly excluded from model features and are read only after predictions are produced to calculate precision/recall/F1 and pattern-level recall.

Real uploaded files do not need either column.

## 5. Human-led decision principle
A flagged row means **suspicious / review recommended**, not proven fraud. The intended workflow is:

- non-flagged transactions -> automated screening clearance,
- flagged transactions -> human review queue,
- later phase -> risk-based supervisor routing.

This mirrors the project principle: technology extends audit capacity; humans retain final judgement.

## Planned next phases
- Phase 3: risk bands + manager/finance/auditor routing.
- Phase 4: richer executive and human-review reports.
- Phase 5: persistent Streamlit analysis state + tester-focused UX.
- Phase 6: unify document-audit results with the same review workflow.
- Phase 7: result-grounded chatbot after core/UI stability.

## 2026-09-03 — Evaluation explainability and systemic-anomaly guardrails

- Added explicit UI/report definitions for synthetic benchmark evaluation, TP/FP/FN/TN, precision, recall, and F1.
- Added transaction-level anomaly drill-down: select a flagged transaction ID and view the audit signals, anomaly reason, cluster distance, isolation score, employee/vendor/category context, and decision.
- Added an external policy signal (`APPROVAL_THRESHOLD`) to the transaction detector. This is independent of within-batch clustering and helps when the uploaded population itself is heavily abnormal.
- Added a distinct `SYSTEMIC REVIEW REQUIRED` batch state when at least 50% of detected transactions are flagged.
- Added `21_systemic_high_anomaly_60.xlsx`, a worst-case benchmark where most of the ledger contains strong injected fraud-like patterns.
- Preserved the core limitation explicitly: clustering/Isolation Forest are relative methods, so majority-abnormal populations can distort the learned notion of "normal". Policy controls and human review remain necessary.

## Phase 3 — Explainable risk scoring and supervisory routing

Phase 2B produced anomaly evidence. Phase 3 converts that evidence into an
operational audit workflow without turning the score into a fraud probability.

New transaction outputs:
- `risk_score` (0-100 transparent review-priority score)
- `risk_level` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
- `risk_components` (weighted evidence contributing to the score)
- `decision`
- `assigned_reviewer`
- `review_required`
- `recommended_action`

Routing policy:
- LOW -> automated screening / normal processing
- MEDIUM -> employee's named manager when available
- HIGH -> Finance Manager / Internal Audit
- CRITICAL -> Senior Auditor / Fraud Investigation

The risk score is intentionally described as a review-priority score rather
than a probability of fraud. The routing layer can also escalate a transaction
based on explicit audit/control evidence even when the unsupervised anomaly
combination alone would not have flagged it. This is intentional human-in-the-
loop defence-in-depth.

## Phase 4 / Phase 5 integration checkpoint — flexible inputs and persistent analysis

- Added conservative automatic schema mapping before canonical validation. Common aliases and small spelling mistakes can map to canonical fields such as `amount`, `date`, `vendor`, and `category`.
- Reduced universal input requirements to the genuinely core fields (`amount`, `date`). Transaction IDs and employee identifiers can be derived when necessary; optional context remains optional.
- Made transaction intelligence signal-aware: if vendor/category/location data is unavailable, dependent checks are skipped rather than fed fabricated placeholders.
- Added schema-mapping and signal-coverage metadata to API responses and audit workbooks.
- Added Streamlit session-state persistence for transaction analysis. Selecting a mini-report transaction, opening sections, or downloading reports reruns the Streamlit script but does not rerun the backend ML pipeline. Results are cleared only through an explicit `New analysis` action.
- Extended professional audit reporting with Schema Mapping and Data Coverage sheets so reviewers can see which inputs were recognized and which fraud signals were unavailable.
- Added evaluation workbooks for typo-tolerant schema mapping and missing-context-field behavior.


## Phase 5 — tester-facing schema requirements and persistent workflow

- Formalized a minimum transaction schema: `transaction_id`, `date`, `amount`, plus `employee_id` OR `employee_name`. The ML pipeline refuses to run when these fields cannot be identified.
- Defined recommended context fields (`vendor`, `category`, `location`, `department`, `manager_name`, `payment_method`) that strengthen fraud signals but are not mandatory. Missing context disables only dependent checks.
- Added a recommended-context coverage score/tier so users can see when analysis is running at minimum, medium, or full contextual strength. This is a data-coverage indicator, not model confidence.
- Added judge-facing minimum and medium-context Excel examples. The medium example intentionally contains misspelled headers to demonstrate conservative fuzzy schema recognition.
- Added transaction-side template/download guidance to mirror the document-audit input guidance.
- Preserved Streamlit session-state caching so drill-downs and downloads do not rerun the backend ML pipeline; only explicit `New analysis` clears the cached result.

## Phase 6 — unified document/transaction review workflow and platform UI

- Added `app/audit/review_workflow.py` as the common operational layer for both audit paths.
- Preserved the original document audit score for backward compatibility while adding a shared `review_priority` using the transaction vocabulary: LOW / MEDIUM / HIGH / CRITICAL.
- Document audits now return `decision`, `assigned_reviewer`, `review_required`, `recommended_action`, `risk_components`, and `audit_reason`, matching the operational fields used by transaction screening.
- Low-scoring documents that still contain a visible WARNING/FAIL are never silently auto-cleared; they are routed to at least MEDIUM human review.
- Refactored transaction routing to reuse the same shared review-priority classification and reviewer hierarchy.
- Added a unified Streamlit navigation shell inspired by an enterprise fraud-screening dashboard: dark left navigation, wide content workspace, KPI strip, central work tables and a right-side insight panel.
- Added Overview, Transaction Analysis, Document Audit, Human Review Queue and Reports pages.
- Document analyses now persist in Streamlit session state just like transaction analyses.
- Added a unified review queue containing both document and transaction items.
- Added a dedicated downloadable document audit workbook with Executive Summary, Findings, Human Review Queue, Extracted Document and Metric Definitions sheets.
- Updated the transaction workbook naming/structure toward an audit-ready Executive Summary / Human Review Queue format.
- Preserved the transaction drill-down as an `st.fragment` so changing the selected transaction updates only the insight section and does not rerun the ML backend.
- Rewrote the public README to match the real Phase-6 architecture, schema policy, reporting, UI and limitations.
- Added shared-workflow tests. Phase 6 checkpoint: 45 tests passing.


## Phase 7 — grounded audit assistant

- Added `app/ai/audit_chat.py`, a retrieval-first conversational layer that consumes only already-computed transaction/document audit results.
- Added deterministic intents for transaction-ID explanations, employee anomaly summaries, department anomaly rates, batch/systemic judgement, risk-policy explanation, schema coverage/skipped signals, unified pending-review counts and document-audit summaries.
- Unsupported questions are rejected instead of answered from general knowledge or guessed context.
- Added an optional Anthropic wording pass. The model receives only the bounded retrieved fact packet plus the deterministic answer; it never receives the raw uploaded document/ledger and cannot recompute risk.
- Added an `Audit Assistant` Streamlit page with persistent chat history, suggested questions, current evidence scope, clear-chat control and explicit capability/limitation guidance.
- The assistant operates over Streamlit-cached results, so conversational interaction does not rerun transaction ML or document extraction.
- Added grounding tests for transaction explanation, employee queries, department aggregation, systemic-batch explanation, schema coverage, document explanation, unified review counts and unsupported questions.
- Phase 7 checkpoint: **53 tests passing**.

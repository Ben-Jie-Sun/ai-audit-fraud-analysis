# AI Audit Assistant

An **AI-assisted** financial document auditing system — not an
"AI decides if it's fraud" system. Deterministic rules and statistical
anomaly detection do the actual judgment work; an LLM only explains
findings that already exist.

```
DOCUMENT
   │
   ▼
Document Parser  ──▶  Structured financial data
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
          Rule-based audit     Anomaly detection
                 │                     │
                 └──────────┬──────────┘
                            ▼
                      Risk findings
                            │
                            ▼
                     AI explanation  (facts → prose, never facts → verdict)
                            │
                            ▼
                   Human auditor report
```

## Why this architecture

- **Rules and stats find issues. The LLM only explains them.** The
  explainer (`app/ai/explainer.py`) receives a JSON list of *already
  computed* findings — ids, statuses, evidence — and is explicitly told
  to treat everything as data, not instructions. It never sees the raw
  document and never assigns risk itself.
- **The uploaded file is untrusted input.** `app/extraction/document_parser.py`
  is the only place raw bytes are touched. Everything downstream reads
  only the structured `ExtractedInvoice` object.
- **Prompt injection is treated as an audit finding, not silently
  filtered.** Free-text fields (vendor, notes, category) are scanned for
  instruction-like patterns during extraction. A hit doesn't block the
  pipeline — it becomes its own visible finding (`AI integrity check`)
  and the raw text is excluded from the LLM prompt, replaced with a
  placeholder.
- **The AI works with zero external dependency.** If no
  `ANTHROPIC_API_KEY` is set (or the call fails for any reason), the
  system falls back to a deterministic template-based summary built
  from the same findings. The demo is never blocked on API access.
- **The risk score is not a fraud probability.** It's called "Audit Risk
  Score" on purpose — a transparent sum of finding weights, always shown
  next to the findings that produced it.

## Project structure

```
ai-audit/
├── app/
│   ├── main.py                  FastAPI app entrypoint
│   ├── api/routes.py             /audit/upload, /audit/sample, /audit/samples
│   ├── audit/
│   │   ├── rules.py               deterministic checks (duplicate, threshold, dates, missing fields, injection)
│   │   ├── anomaly.py             statistical amount-vs-category-median check
│   │   └── scoring.py             combine findings → 0-100 score + LOW/MEDIUM/HIGH
│   ├── extraction/document_parser.py   parse + sanitize CSV/JSON/PDF/image uploads
│   ├── ai/explainer.py            LLM summary generator + template fallback
│   └── models/schemas.py          shared Pydantic models
├── data/
│   ├── raw/                       (gitignored scratch space for real uploads)
│   └── sample/                    synthetic historical ledger + 5 demo invoices
├── frontend/streamlit_app.py      dashboard UI (calls the FastAPI backend)
├── tests/                         pytest suite for rules, anomaly, scoring, injection scanning
├── config.py                      non-secret settings (thresholds, paths, model name)
├── .env.example                   secrets template (copy to .env)
└── requirements.txt
```

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # optionally add ANTHROPIC_API_KEY
```

PDF and image support need their libraries too (`pdfplumber`,
`pytesseract` + the `tesseract` binary, `Pillow`) — already listed in
`requirements.txt`. If you only care about the JSON/CSV demo flow, you
can skip installing the OCR/PDF stack entirely; those paths raise a
clear error instead of failing silently.

## Run it

Backend:

```bash
uvicorn app.main:app --reload
```

Frontend (in a second terminal):

```bash
streamlit run frontend/streamlit_app.py
```

Open the Streamlit URL it prints, then either upload a document or use
the **Try a sample** tab to run one of the five bundled demo invoices
against the real pipeline with one click:

| Sample file                     | Demonstrates                                    |
|----------------------------------|--------------------------------------------------|
| `invoice_normal.json`            | Everything passes → LOW RISK                     |
| `invoice_high_risk.json`         | Amount anomaly + over approval threshold → HIGH  |
| `invoice_duplicate.json`         | Same vendor + invoice number already in history  |
| `invoice_missing_fields.json`    | Missing vendor/invoice number                    |
| `invoice_injection.json`         | Notes field contains a prompt-injection attempt  |

You can also hit the API directly — interactive docs at
`http://127.0.0.1:8000/docs`.

## Run the tests

```bash
pytest
```

Covers the rule engine, anomaly detection, risk scoring, and the
prompt-injection scanner — all pure functions, no API key or network
needed.

## Configuration

Non-secret thresholds live in `config.py` (approval threshold, anomaly
ratio, duplicate-amount tolerance, risk bands) — change these to tune
the demo without touching any logic. Secrets (`ANTHROPIC_API_KEY`,
`DATABASE_URL`) live only in `.env`, which is gitignored; `.env.example`
is committed instead.

## What this intentionally does NOT do

- No fraud "verdict" from the model — only a human-readable explanation
  of pre-computed findings, plus a suggested next action.
- No claim that the risk score is a calibrated probability.
- No Kubernetes, microservices, custom ML models, or heavy MLOps — this
  is a lightweight stack (FastAPI + Streamlit + pandas + SQLite/JSON)
  sized for a short build, not a production audit platform.

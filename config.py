"""
Non-secret application configuration.

Secrets (API keys, DB URLs) live in .env / environment variables and are
loaded separately in app/ai/explainer.py — they never live here and this
file never reads .env directly, so this module is always safe to import,
log, or commit.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # populates os.environ from a local .env file, if present

# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {".pdf", ".csv", ".json", ".png", ".jpg", ".jpeg"}

# ---------------------------------------------------------------------------
# Audit engine thresholds
# ---------------------------------------------------------------------------
# Amount above which an invoice requires additional approval, regardless
# of category. Currency-agnostic; the demo data uses INR.
APPROVAL_THRESHOLD = 100_000

# Anomaly detection: how many multiples of the historical category median
# a transaction can be before it's flagged.
ANOMALY_RATIO_THRESHOLD = 2.5

# Duplicate detection: how close two amounts must be (as a fraction) to be
# considered "the same" transaction for duplicate-invoice-number checks.
DUPLICATE_AMOUNT_TOLERANCE = 0.02  # 2%

# Risk score bands (0-100)
RISK_BAND_LOW_MAX = 30
RISK_BAND_MEDIUM_MAX = 65
# anything above RISK_BAND_MEDIUM_MAX is HIGH RISK

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample")
RAW_DIR = os.path.join(DATA_DIR, "raw")
HISTORICAL_TRANSACTIONS_PATH = os.path.join(SAMPLE_DIR, "historical_transactions.csv")

# ---------------------------------------------------------------------------
# Non-secret AI configuration
# ---------------------------------------------------------------------------
# The model name is not a secret. Whether a key is present or not is read
# lazily inside app/ai/explainer.py so importing config never touches secrets.
LLM_MODEL = "claude-sonnet-4-6"
LLM_MAX_TOKENS = 600

# API backend location for the Streamlit frontend
API_BASE_URL = os.environ.get("AUDIT_API_BASE_URL", "http://127.0.0.1:8000")

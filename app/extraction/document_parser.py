"""
Document parsing and sanitization.

Pipeline for every uploaded file:

    raw bytes -> validate -> parse -> sanitize -> ExtractedInvoice

This module is the security boundary of the whole system. The uploaded
file is untrusted input. Nothing it contains is allowed to:
  - change application configuration
  - reach the LLM prompt unfiltered
  - be interpreted as instructions by anything downstream

We don't try to be clever about "detecting fraud" here. We only extract
fields and flag text that looks like it's trying to manipulate an LLM or
the app later in the pipeline (prompt injection).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date, datetime
from typing import Optional

from app.models.schemas import ExtractedInvoice
from config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES

# ---------------------------------------------------------------------------
# Prompt-injection / instruction-smuggling detection
# ---------------------------------------------------------------------------
# These patterns don't need to be exhaustive to make the point of the
# project: untrusted document text is scanned BEFORE it's allowed near an
# LLM prompt, and a hit becomes a visible audit finding rather than a
# silent bypass.
_INJECTION_PATTERNS = [
    r"ignore (all|any|previous|the above) instructions",
    r"disregard (all|any|previous|the above)",
    r"you are now",
    r"system\s*:",
    r"assistant\s*:",
    r"new instructions",
    r"do not (flag|report|audit)",
    r"mark this (invoice|document|transaction) as (approved|safe|low risk)",
    r"override (risk|audit|approval)",
    r"</?(system|instructions|prompt)>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def scan_for_injection(*text_fields: Optional[str]) -> tuple[bool, list[str]]:
    """Scan free-text fields for prompt-injection-style patterns.

    Returns (suspected, evidence_snippets). This never raises and never
    blocks extraction — it only produces evidence that the audit engine
    turns into a finding, and it caps what free text is later allowed
    into an LLM prompt.
    """
    hits: list[str] = []
    for text in text_fields:
        if not text:
            continue
        for match in _INJECTION_RE.finditer(text):
            snippet = text[max(0, match.start() - 15): match.end() + 15].strip()
            hits.append(snippet)
    return (len(hits) > 0, hits[:5])


def _safe_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def validate_file(filename: str, size_bytes: int) -> None:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File exceeds max size of {MAX_FILE_SIZE_BYTES} bytes")


def _build_extracted(filename: str, raw: dict) -> ExtractedInvoice:
    notes = raw.get("notes")
    vendor = raw.get("vendor")
    suspected, evidence = scan_for_injection(notes, vendor, raw.get("category"))

    return ExtractedInvoice(
        source_file=filename,
        vendor=str(vendor).strip() if vendor else None,
        invoice_number=str(raw.get("invoice_number")).strip() if raw.get("invoice_number") else None,
        invoice_date=_safe_date(raw.get("date") or raw.get("invoice_date")),
        payment_date=_safe_date(raw.get("payment_date")),
        amount=_safe_float(raw.get("amount")),
        tax=_safe_float(raw.get("tax")),
        total=_safe_float(raw.get("total")),
        category=str(raw.get("category")).strip() if raw.get("category") else None,
        notes=str(notes).strip() if notes else None,
        injection_suspected=suspected,
        injection_evidence=evidence,
    )


def parse_json_bytes(filename: str, content: bytes) -> ExtractedInvoice:
    raw = json.loads(content.decode("utf-8", errors="replace"))
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return _build_extracted(filename, raw)


def parse_csv_bytes(filename: str, content: bytes) -> ExtractedInvoice:
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV file contains no data rows")
    return _build_extracted(filename, rows[0])


def parse_pdf_bytes(filename: str, content: bytes) -> ExtractedInvoice:
    """Extract text from a PDF and pull out invoice-shaped fields with
    lightweight regexes. Good enough for a hackathon demo; a production
    system would use a proper document-AI extraction step here instead.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required to parse PDF invoices (pip install pdfplumber)"
        ) from exc

    text_parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    full_text = "\n".join(text_parts)

    def _find(pattern, default=None):
        m = re.search(pattern, full_text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    raw = {
        "vendor": _find(r"vendor[:\s]+([^\n]+)"),
        "invoice_number": _find(r"invoice\s*(?:no|number|#)[:\s]+([A-Za-z0-9\-]+)"),
        "date": _find(r"(?:invoice\s*)?date[:\s]+([0-9/\-]+)"),
        "amount": _find(r"amount[:\s]+₹?\s*([0-9,\.]+)"),
        "tax": _find(r"tax[:\s]+₹?\s*([0-9,\.]+)"),
        "total": _find(r"total[:\s]+₹?\s*([0-9,\.]+)"),
        "category": _find(r"category[:\s]+([^\n]+)"),
        "notes": _find(r"notes?[:\s]+([^\n]+)"),
    }
    return _build_extracted(filename, raw)


def parse_document(filename: str, content: bytes) -> ExtractedInvoice:
    """Dispatch to the right parser based on file extension."""
    validate_file(filename, len(content))
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".json":
        return parse_json_bytes(filename, content)
    if ext == ".csv":
        return parse_csv_bytes(filename, content)
    if ext == ".pdf":
        return parse_pdf_bytes(filename, content)
    if ext in (".png", ".jpg", ".jpeg"):
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract and Pillow are required to parse image invoices"
            ) from exc
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image)

        def _find(pattern, default=None):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else default

        raw = {
            "vendor": _find(r"vendor[:\s]+([^\n]+)"),
            "invoice_number": _find(r"invoice\s*(?:no|number|#)[:\s]+([A-Za-z0-9\-]+)"),
            "date": _find(r"(?:invoice\s*)?date[:\s]+([0-9/\-]+)"),
            "amount": _find(r"amount[:\s]+₹?\s*([0-9,\.]+)"),
            "tax": _find(r"tax[:\s]+₹?\s*([0-9,\.]+)"),
            "total": _find(r"total[:\s]+₹?\s*([0-9,\.]+)"),
            "category": _find(r"category[:\s]+([^\n]+)"),
            "notes": _find(r"notes?[:\s]+([^\n]+)"),
        }
        return _build_extracted(filename, raw)

    raise ValueError(f"No parser available for extension '{ext}'")

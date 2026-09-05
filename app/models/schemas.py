"""
Shared data models.

ExtractedInvoice is the ONE representation the rest of the system trusts.
Everything downstream (rules, anomaly detection, scoring, the LLM
explainer) reads only from this structured object — never from the raw
uploaded file. That boundary is what makes the raw document's contents
inert as far as the audit logic and the LLM prompt are concerned.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FindingStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class RiskLevel(str, Enum):
    LOW = "LOW RISK"
    MEDIUM = "MEDIUM RISK"
    HIGH = "HIGH RISK"


class ExtractedInvoice(BaseModel):
    """Structured financial data pulled out of an uploaded document.

    Every field here is exactly what the audit engine and the LLM are
    allowed to see and reason about. If a field isn't here, it doesn't
    exist as far as the rest of the pipeline is concerned.
    """

    source_file: str
    vendor: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    payment_date: Optional[date] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    category: Optional[str] = None
    notes: Optional[str] = None

    # Populated by the sanitizer during extraction. True if any free-text
    # field contained a pattern resembling an attempt to steer an LLM or
    # the application (e.g. "ignore previous instructions", fake
    # "system:" headers). This never blocks the audit — it becomes its
    # own finding — but it does control what text is allowed anywhere
    # near a prompt.
    injection_suspected: bool = False
    injection_evidence: list[str] = Field(default_factory=list)

class Transaction(BaseModel):
    """
    Structured representation of one financial transaction.

    This will be used for CSV/Excel transaction ledgers.
    """

    transaction_id: str
    employee_id: str
    employee_name: str
    date: date
    vendor: str
    category: str
    amount: float

    manager_name: Optional[str] = None
    department: Optional[str] = None
    payment_method: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

class Evidence(BaseModel):
    label: str
    value: str


class Finding(BaseModel):
    id: str
    title: str
    status: FindingStatus
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)
    weight: int = Field(description="Contribution to the risk score if not PASS")


class AuditResult(BaseModel):
    source_file: str
    extracted: ExtractedInvoice
    findings: list[Finding]
    risk_score: int
    risk_level: RiskLevel
    ai_summary: str
    ai_summary_source: str  # "llm" or "template_fallback"

    # Phase 6 operational workflow. ``risk_level`` above is retained for
    # backward compatibility with the original document-audit API; the shared
    # review workflow uses the same LOW/MEDIUM/HIGH/CRITICAL terminology as
    # transaction analysis.
    review_priority: str
    decision: str
    assigned_reviewer: str
    review_required: bool
    recommended_action: str
    risk_components: str
    audit_reason: str

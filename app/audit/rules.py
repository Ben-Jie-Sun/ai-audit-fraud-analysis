"""
Deterministic audit rules.

Every rule here is plain, inspectable Python logic — no model calls, no
probabilistic judgment. Given the same ExtractedInvoice (and the same
history/config), a rule always produces the same Finding. That
determinism is the whole point: an auditor can reproduce and defend
every FAIL/WARNING without trusting a black box.

Each rule returns a single Finding, always — including a PASS finding
when nothing is wrong, so the dashboard can show a full checklist.
"""

from __future__ import annotations

import pandas as pd

from app.models.schemas import Evidence, ExtractedInvoice, Finding, FindingStatus
from config import APPROVAL_THRESHOLD, DUPLICATE_AMOUNT_TOLERANCE


def check_missing_fields(invoice: ExtractedInvoice) -> Finding:
    required = {
        "vendor": invoice.vendor,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "amount": invoice.amount,
    }
    missing = [name for name, value in required.items() if value in (None, "")]

    if missing:
        return Finding(
            id="missing_fields",
            title="Required fields",
            status=FindingStatus.FAIL,
            detail=f"Missing required field(s): {', '.join(missing)}.",
            evidence=[Evidence(label="Missing fields", value=", ".join(missing))],
            weight=20,
        )
    return Finding(
        id="missing_fields",
        title="Required fields",
        status=FindingStatus.PASS,
        detail="All required fields are present.",
        evidence=[],
        weight=0,
    )


def check_threshold(invoice: ExtractedInvoice) -> Finding:
    amount = invoice.total if invoice.total is not None else invoice.amount
    if amount is None:
        return Finding(
            id="approval_threshold",
            title="Approval threshold",
            status=FindingStatus.WARNING,
            detail="Amount unavailable — threshold could not be checked.",
            evidence=[],
            weight=5,
        )

    if amount > APPROVAL_THRESHOLD:
        return Finding(
            id="approval_threshold",
            title="Approval threshold",
            status=FindingStatus.FAIL,
            detail="Transaction amount exceeds the configured approval threshold.",
            evidence=[
                Evidence(label="Invoice amount", value=f"₹{amount:,.2f}"),
                Evidence(label="Approval threshold", value=f"₹{APPROVAL_THRESHOLD:,.2f}"),
            ],
            weight=25,
        )
    return Finding(
        id="approval_threshold",
        title="Approval threshold",
        status=FindingStatus.PASS,
        detail="Amount is within the approval threshold.",
        evidence=[Evidence(label="Invoice amount", value=f"₹{amount:,.2f}")],
        weight=0,
    )


def check_date_anomaly(invoice: ExtractedInvoice) -> Finding:
    if invoice.invoice_date is None or invoice.payment_date is None:
        return Finding(
            id="date_anomaly",
            title="Date consistency",
            status=FindingStatus.PASS,
            detail="No payment date provided to compare against invoice date.",
            evidence=[],
            weight=0,
        )

    if invoice.invoice_date > invoice.payment_date:
        return Finding(
            id="date_anomaly",
            title="Date consistency",
            status=FindingStatus.FAIL,
            detail="Invoice date is after the recorded payment date.",
            evidence=[
                Evidence(label="Invoice date", value=str(invoice.invoice_date)),
                Evidence(label="Payment date", value=str(invoice.payment_date)),
            ],
            weight=15,
        )
    return Finding(
        id="date_anomaly",
        title="Date consistency",
        status=FindingStatus.PASS,
        detail="Invoice date precedes the payment date, as expected.",
        evidence=[
            Evidence(label="Invoice date", value=str(invoice.invoice_date)),
            Evidence(label="Payment date", value=str(invoice.payment_date)),
        ],
        weight=0,
    )


def check_duplicate(invoice: ExtractedInvoice, historical: pd.DataFrame) -> Finding:
    """Flag a likely duplicate: same vendor + same invoice number (or a
    very close amount match) already present in the historical ledger.
    """
    if historical.empty or not invoice.vendor or not invoice.invoice_number:
        return Finding(
            id="duplicate_invoice",
            title="Duplicate invoice",
            status=FindingStatus.PASS,
            detail="No matching vendor/invoice-number history to compare against.",
            evidence=[],
            weight=0,
        )

    same_vendor = historical[
        historical["vendor"].str.strip().str.lower() == invoice.vendor.strip().lower()
    ]

    exact_number_match = same_vendor[
        same_vendor["invoice_number"].astype(str).str.strip()
        == str(invoice.invoice_number).strip()
    ]

    if not exact_number_match.empty:
        prior = exact_number_match.iloc[0]
        return Finding(
            id="duplicate_invoice",
            title="Duplicate invoice",
            status=FindingStatus.FAIL,
            detail="An invoice with the same vendor and invoice number already exists in history.",
            evidence=[
                Evidence(label="Vendor", value=invoice.vendor),
                Evidence(label="Invoice number", value=invoice.invoice_number),
                Evidence(label="Prior amount", value=f"₹{float(prior['amount']):,.2f}"),
                Evidence(label="Prior date", value=str(prior["date"])),
            ],
            weight=30,
        )

    if invoice.amount is not None and not same_vendor.empty:
        close_amount = same_vendor[
            (same_vendor["amount"] - invoice.amount).abs()
            <= invoice.amount * DUPLICATE_AMOUNT_TOLERANCE
        ]
        if not close_amount.empty:
            prior = close_amount.iloc[0]
            return Finding(
                id="duplicate_invoice",
                title="Duplicate invoice",
                status=FindingStatus.WARNING,
                detail="Vendor has a prior transaction with a very similar amount.",
                evidence=[
                    Evidence(label="Vendor", value=invoice.vendor),
                    Evidence(label="Current amount", value=f"₹{invoice.amount:,.2f}"),
                    Evidence(label="Prior amount", value=f"₹{float(prior['amount']):,.2f}"),
                    Evidence(label="Prior invoice #", value=str(prior["invoice_number"])),
                ],
                weight=15,
            )

    return Finding(
        id="duplicate_invoice",
        title="Duplicate invoice",
        status=FindingStatus.PASS,
        detail="No duplicate or near-duplicate transaction found for this vendor.",
        evidence=[],
        weight=0,
    )


def check_prompt_injection(invoice: ExtractedInvoice) -> Finding:
    """Surface any suspected prompt-injection content found during
    extraction as a first-class audit finding, rather than silently
    filtering it. This is an AI-reliability control, not a fraud rule.
    """
    if not invoice.injection_suspected:
        return Finding(
            id="ai_integrity",
            title="AI integrity check",
            status=FindingStatus.PASS,
            detail="No instruction-like text detected in document fields.",
            evidence=[],
            weight=0,
        )

    return Finding(
        id="ai_integrity",
        title="AI integrity check",
        status=FindingStatus.WARNING,
        detail=(
            "Document text contains patterns resembling an attempt to steer "
            "an AI system or bypass audit logic. This text was excluded from "
            "the AI explanation and is shown here for human review only."
        ),
        evidence=[
            Evidence(label=f"Suspicious text {i+1}", value=snippet)
            for i, snippet in enumerate(invoice.injection_evidence)
        ],
        weight=10,
    )


def run_all_rules(invoice: ExtractedInvoice, historical: pd.DataFrame) -> list[Finding]:
    return [
        check_missing_fields(invoice),
        check_threshold(invoice),
        check_date_anomaly(invoice),
        check_duplicate(invoice, historical),
        check_prompt_injection(invoice),
    ]

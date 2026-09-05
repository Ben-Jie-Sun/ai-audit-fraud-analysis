"""Shared human-review routing for document and transaction audit results.

The project deliberately separates *detection evidence* from the operational
workflow. Models and deterministic rules produce evidence and a transparent
0-100 review-priority score. This module converts that score into a common
LOW/MEDIUM/HIGH/CRITICAL queue and assigns a human reviewer.

The score and risk band are not probabilities of fraud.
"""

from __future__ import annotations

from app.models.schemas import Finding, FindingStatus


RISK_BAND_MEDIUM_MIN = 25
RISK_BAND_HIGH_MIN = 50
RISK_BAND_CRITICAL_MIN = 75


def classify_review_priority(score: int) -> str:
    """Classify a 0-100 review-priority score using one shared policy."""
    bounded = max(0, min(int(score), 100))
    if bounded >= RISK_BAND_CRITICAL_MIN:
        return "CRITICAL"
    if bounded >= RISK_BAND_HIGH_MIN:
        return "HIGH"
    if bounded >= RISK_BAND_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def route_review(
    risk_level: str,
    *,
    source_type: str,
    manager_name: str | None = None,
) -> tuple[str, str, bool, str]:
    """Return decision, reviewer, review-required flag and recommended action.

    ``source_type`` changes only the MEDIUM reviewer because transaction ledgers
    can contain an employee manager, while standalone invoice documents usually
    do not. HIGH and CRITICAL use the same finance/audit escalation hierarchy.
    """
    level = str(risk_level).upper().strip()

    if level == "LOW":
        return (
            "AUTO-CLEARED",
            "Automated screening",
            False,
            "Proceed through normal automated processing.",
        )

    if level == "MEDIUM":
        if source_type == "transaction":
            reviewer = (manager_name or "Line Manager").strip() or "Line Manager"
            action = "Manager should verify supporting evidence and business purpose."
        else:
            reviewer = "Accounts Payable / Line Manager"
            action = "Verify the document against supporting records before approval or payment."
        return ("MANAGER REVIEW", reviewer, True, action)

    if level == "HIGH":
        return (
            "FINANCE REVIEW",
            "Finance Manager / Internal Auditor",
            True,
            "Finance/Internal Audit review is required before approval or settlement.",
        )

    return (
        "CRITICAL ESCALATION",
        "Senior Auditor / Fraud Investigation",
        True,
        "Hold processing and escalate for senior audit or fraud investigation.",
    )


def build_document_review_workflow(findings: list[Finding], risk_score: int) -> dict:
    """Build the shared operational workflow for a standalone document audit.

    A low numerical score can still contain a material document-control warning
    (for example prompt-injection-like text or a missing required field). Such a
    document is raised to MEDIUM so that visible non-pass evidence is never
    silently auto-cleared.
    """
    non_pass = [
        finding
        for finding in findings
        if finding.status in (FindingStatus.WARNING, FindingStatus.FAIL)
    ]

    priority = classify_review_priority(risk_score)
    if non_pass and priority == "LOW":
        priority = "MEDIUM"

    decision, reviewer, required, action = route_review(
        priority,
        source_type="document",
    )

    if non_pass:
        components = "; ".join(
            f"{finding.title}: {finding.detail}"
            for finding in non_pass
        )
        reason = (
            f"{priority} review priority ({int(risk_score)}/100). "
            f"{len(non_pass)} non-pass audit finding(s): {components}"
        )
    else:
        components = "No material audit findings triggered"
        reason = (
            f"{priority} review priority ({int(risk_score)}/100). "
            "All deterministic document checks passed."
        )

    return {
        "review_priority": priority,
        "decision": decision,
        "assigned_reviewer": reviewer,
        "review_required": required,
        "recommended_action": action,
        "risk_components": components,
        "audit_reason": reason,
    }

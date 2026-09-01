"""
Risk scoring.

The score is a transparent, additive combination of finding weights —
NOT a calibrated probability of fraud. We call it "Audit Risk Score" on
purpose and always show how it was built, so nobody mistakes 72/100 for
"72% likely fraudulent."

    score = min(100, sum(weight for findings that are WARNING or FAIL))
"""

from __future__ import annotations

from app.models.schemas import Finding, FindingStatus, RiskLevel
from config import RISK_BAND_LOW_MAX, RISK_BAND_MEDIUM_MAX


def compute_risk_score(findings: list[Finding]) -> int:
    total = sum(
        f.weight for f in findings if f.status in (FindingStatus.WARNING, FindingStatus.FAIL)
    )
    return min(100, total)


def classify_risk(score: int) -> RiskLevel:
    if score <= RISK_BAND_LOW_MAX:
        return RiskLevel.LOW
    if score <= RISK_BAND_MEDIUM_MAX:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH

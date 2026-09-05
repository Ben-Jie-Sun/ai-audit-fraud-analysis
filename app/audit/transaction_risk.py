"""Explainable transaction risk scoring and supervisory routing.

This module turns Phase-2B anomaly evidence into an operational audit action.
The score is a transparent review-priority score from 0 to 100. It is NOT a
probability that fraud occurred.
"""

from __future__ import annotations

import pandas as pd

from app.audit.review_workflow import classify_review_priority, route_review


RISK_WEIGHTS = {
    "isolation_outlier": 15,
    "cluster_outlier": 15,
    "pattern_duplicate_payment": 30,
    "pattern_split_payment": 35,
    "pattern_vendor_burst": 25,
    "pattern_employee_burst": 10,
    "pattern_category_shift": 12,
    "pattern_location_shift": 12,
    "pattern_rounded_repeat": 10,
    "pattern_amount_deviation": 25,
    "pattern_approval_threshold_exceeded": 25,
}

RISK_LABELS = {
    "isolation_outlier": "Isolation Forest deviation",
    "cluster_outlier": "behavioural cluster deviation",
    "pattern_duplicate_payment": "duplicate-payment pattern",
    "pattern_split_payment": "split-payment pattern",
    "pattern_vendor_burst": "vendor payment burst",
    "pattern_employee_burst": "employee transaction burst",
    "pattern_category_shift": "unusual category shift",
    "pattern_location_shift": "unusual location shift",
    "pattern_rounded_repeat": "repeated rounded-value pattern",
    "pattern_amount_deviation": "amount deviation",
    "pattern_approval_threshold_exceeded": "approval threshold exceeded",
}


def classify_transaction_risk(score: int) -> str:
    """Backward-compatible wrapper around the shared review policy."""
    return classify_review_priority(score)


def _routing_for_row(row: pd.Series, risk_level: str) -> tuple[str, str, bool]:
    """Return (decision, assigned reviewer, review_required)."""
    decision, reviewer, required, _ = route_review(
        risk_level,
        source_type="transaction",
        manager_name=str(row.get("manager_name") or "").strip() or None,
    )
    return decision, reviewer, required


def apply_transaction_risk_routing(transactions: pd.DataFrame) -> pd.DataFrame:
    """Add explainable risk, reviewer and audit-decision columns.

    The input is expected to have already passed through
    ``detect_transaction_anomalies``. Risk is based only on model/pattern
    evidence produced by the audit engine, never on benchmark labels such as
    ``synthetic_anomaly`` or ``anomaly_type``.
    """
    result = transactions.copy()

    missing = [column for column in RISK_WEIGHTS if column not in result.columns]
    if missing:
        raise ValueError(
            "Transaction risk routing requires anomaly evidence columns: "
            + ", ".join(sorted(missing))
        )

    scores = pd.Series(0, index=result.index, dtype=int)
    contribution_text: list[str] = []

    for index, row in result.iterrows():
        contributions: list[str] = []
        score = 0
        for column, weight in RISK_WEIGHTS.items():
            if bool(row.get(column, False)):
                score += weight
                contributions.append(f"{RISK_LABELS[column]} (+{weight})")

        score = min(score, 100)
        scores.loc[index] = score
        contribution_text.append(
            "; ".join(contributions)
            if contributions
            else "No material risk signals triggered"
        )

    result["risk_score"] = scores.astype(int)
    result["risk_level"] = result["risk_score"].map(classify_transaction_risk)
    result["risk_components"] = contribution_text

    decisions: list[str] = []
    reviewers: list[str] = []
    review_flags: list[bool] = []
    actions: list[str] = []

    for _, row in result.iterrows():
        level = str(row["risk_level"])
        decision, reviewer, required = _routing_for_row(row, level)
        _, _, _, action = route_review(
            level,
            source_type="transaction",
            manager_name=str(row.get("manager_name") or "").strip() or None,
        )
        decisions.append(decision)
        reviewers.append(reviewer)
        review_flags.append(required)
        actions.append(action)

    result["decision"] = decisions
    result["assigned_reviewer"] = reviewers
    result["review_required"] = review_flags
    result["recommended_action"] = actions

    result["audit_reason"] = result.apply(
        lambda row: (
            f"{row['risk_level']} review priority ({int(row['risk_score'])}/100). "
            f"{row['risk_components']}."
        ),
        axis=1,
    )

    return result


def summarize_transaction_risk(transactions: pd.DataFrame) -> dict:
    """Return dashboard/report summaries for the routed transaction ledger."""
    if "risk_level" not in transactions.columns:
        raise ValueError("Risk routing must run before risk summarization.")

    counts = transactions["risk_level"].value_counts().to_dict()
    review_queue = transactions[transactions["review_required"].astype(bool)]

    return {
        "low": int(counts.get("LOW", 0)),
        "medium": int(counts.get("MEDIUM", 0)),
        "high": int(counts.get("HIGH", 0)),
        "critical": int(counts.get("CRITICAL", 0)),
        "review_required": int(len(review_queue)),
        "auto_cleared": int((transactions["decision"] == "AUTO-CLEARED").sum()),
    }

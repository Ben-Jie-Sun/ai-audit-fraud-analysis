import pandas as pd

from app.audit.anomaly import detect_transaction_anomalies
from app.audit.transaction_risk import (
    apply_transaction_risk_routing,
    classify_transaction_risk,
    summarize_transaction_risk,
)


def _ledger(rows: int = 60) -> pd.DataFrame:
    data = []
    for i in range(rows):
        data.append(
            {
                "transaction_id": f"TX{i:04d}",
                "employee_id": f"EMP{i % 5}",
                "employee_name": f"Employee {i % 5}",
                "manager_name": f"Manager {i % 3}",
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i % 30),
                "vendor": f"Vendor {i % 7}",
                "category": f"Category {i % 4}",
                "amount": 1000.0 + (i % 8) * 50.0,
                "department": "Finance",
                "location": "Delhi",
            }
        )
    data[-1]["amount"] = 250000.0
    return pd.DataFrame(data)


def test_risk_band_boundaries():
    assert classify_transaction_risk(0) == "LOW"
    assert classify_transaction_risk(24) == "LOW"
    assert classify_transaction_risk(25) == "MEDIUM"
    assert classify_transaction_risk(50) == "HIGH"
    assert classify_transaction_risk(75) == "CRITICAL"
    assert classify_transaction_risk(100) == "CRITICAL"


def test_risk_routing_adds_operational_columns():
    detected = detect_transaction_anomalies(_ledger())
    routed = apply_transaction_risk_routing(detected)
    expected = {
        "risk_score",
        "risk_level",
        "risk_components",
        "decision",
        "assigned_reviewer",
        "review_required",
        "recommended_action",
        "audit_reason",
    }
    assert expected.issubset(routed.columns)
    assert routed["risk_score"].between(0, 100).all()


def test_medium_risk_routes_to_named_manager():
    row = _ledger(10).iloc[[0]].copy()
    evidence_columns = {
        "isolation_outlier": True,
        "cluster_outlier": True,
        "pattern_duplicate_payment": False,
        "pattern_split_payment": False,
        "pattern_vendor_burst": False,
        "pattern_employee_burst": False,
        "pattern_category_shift": False,
        "pattern_location_shift": False,
        "pattern_rounded_repeat": False,
        "pattern_amount_deviation": False,
        "pattern_approval_threshold_exceeded": False,
    }
    for column, value in evidence_columns.items():
        row[column] = value
    routed = apply_transaction_risk_routing(row)
    assert routed.iloc[0]["risk_level"] == "MEDIUM"
    assert routed.iloc[0]["assigned_reviewer"] == row.iloc[0]["manager_name"]
    assert bool(routed.iloc[0]["review_required"]) is True


def test_critical_combination_escalates_to_senior_audit():
    row = _ledger(10).iloc[[0]].copy()
    for column in (
        "isolation_outlier",
        "cluster_outlier",
        "pattern_duplicate_payment",
        "pattern_split_payment",
        "pattern_vendor_burst",
        "pattern_employee_burst",
        "pattern_category_shift",
        "pattern_location_shift",
        "pattern_rounded_repeat",
        "pattern_amount_deviation",
        "pattern_approval_threshold_exceeded",
    ):
        row[column] = True
    routed = apply_transaction_risk_routing(row)
    assert routed.iloc[0]["risk_score"] == 100
    assert routed.iloc[0]["risk_level"] == "CRITICAL"
    assert routed.iloc[0]["decision"] == "CRITICAL ESCALATION"
    assert "Senior Auditor" in routed.iloc[0]["assigned_reviewer"]


def test_risk_summary_matches_rows():
    routed = apply_transaction_risk_routing(detect_transaction_anomalies(_ledger()))
    summary = summarize_transaction_risk(routed)
    assert summary["low"] + summary["medium"] + summary["high"] + summary["critical"] == len(routed)
    assert summary["review_required"] == int(routed["review_required"].sum())


def test_every_flagged_anomaly_requires_review():
    routed = apply_transaction_risk_routing(detect_transaction_anomalies(_ledger(120)))
    flagged = routed[routed["is_anomaly"]]
    assert not flagged.empty
    assert flagged["review_required"].all()
    assert (flagged["risk_score"] >= 25).all()

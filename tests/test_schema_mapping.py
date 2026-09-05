from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.audit.anomaly import detect_transaction_anomalies
from app.audit.transaction_risk import apply_transaction_risk_routing
from app.extraction.transaction_parser import load_transaction_file, map_transaction_schema


def test_schema_mapping_handles_aliases_and_spelling_variation() -> None:
    raw = pd.DataFrame(
        {
            "Txn ID": ["T1", "T2", "T3", "T4", "T5", "T6"],
            "Emplyee ID": ["E1", "E1", "E2", "E2", "E3", "E3"],
            "Transaction Date": pd.date_range("2026-01-01", periods=6),
            "Merchent": ["A", "A", "B", "B", "C", "C"],
            "Expense Catagory": ["Office"] * 6,
            "Value": [1000, 1100, 1200, 1300, 1400, 1500],
        }
    )

    mapped, report = map_transaction_schema(raw)
    assert "transaction_id" in mapped.columns
    assert "employee_id" in mapped.columns
    assert "date" in mapped.columns
    assert "vendor" in mapped.columns
    assert "category" in mapped.columns
    assert "amount" in mapped.columns
    assert any(row["method"] == "fuzzy" for row in report)


def test_missing_vendor_category_location_skips_dependent_signals(tmp_path: Path) -> None:
    rows = 40
    df = pd.DataFrame(
        {
            "transaction id": [f"T{i:03d}" for i in range(rows)],
            "employee id": [f"E{i % 5}" for i in range(rows)],
            "transaction date": pd.date_range("2026-01-01", periods=rows),
            "amount": [1000 + i * 10 for i in range(rows)],
        }
    )
    path = tmp_path / "minimal.xlsx"
    df.to_excel(path, index=False)

    loaded = load_transaction_file(str(path))
    coverage = loaded.attrs["data_coverage"]
    assert "vendor frequency" in coverage["skipped_signals"]
    assert "category deviation" in coverage["skipped_signals"]
    assert "location shift" in coverage["skipped_signals"]

    analysed = detect_transaction_anomalies(loaded)
    routed = apply_transaction_risk_routing(analysed)

    assert "pattern_vendor_burst" in routed.columns
    assert not routed["pattern_vendor_burst"].any()
    assert not routed["pattern_split_payment"].any()
    assert not routed["pattern_category_shift"].any()
    assert not routed["pattern_location_shift"].any()


def test_minimum_schema_requires_transaction_id(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "employee id": ["E1", "E2"],
            "transaction date": ["2026-01-01", "2026-01-02"],
            "amount": [1000, 1200],
        }
    )
    path = tmp_path / "missing_transaction_id.xlsx"
    df.to_excel(path, index=False)

    try:
        load_transaction_file(str(path))
    except ValueError as exc:
        assert "transaction_id" in str(exc)
    else:
        raise AssertionError("Missing transaction ID should fail minimum-schema validation")


def test_minimum_schema_requires_employee_identity(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "transaction id": ["T1", "T2"],
            "transaction date": ["2026-01-01", "2026-01-02"],
            "amount": [1000, 1200],
        }
    )
    path = tmp_path / "missing_employee.xlsx"
    df.to_excel(path, index=False)

    try:
        load_transaction_file(str(path))
    except ValueError as exc:
        assert "employee identity" in str(exc).lower()
    else:
        raise AssertionError("Missing employee identity should fail minimum-schema validation")


def test_coverage_metadata_reports_recommended_context(tmp_path: Path) -> None:
    rows = 12
    df = pd.DataFrame(
        {
            "transaction id": [f"T{i:03d}" for i in range(rows)],
            "employee id": [f"E{i % 3}" for i in range(rows)],
            "transaction date": pd.date_range("2026-01-01", periods=rows),
            "amount": [1000 + i * 50 for i in range(rows)],
            "merchant": ["Vendor A"] * rows,
            "expense category": ["Office"] * rows,
            "department": ["Operations"] * rows,
        }
    )
    path = tmp_path / "medium_context.xlsx"
    df.to_excel(path, index=False)

    loaded = load_transaction_file(str(path))
    coverage = loaded.attrs["data_coverage"]
    assert coverage["schema_tier"] == "MEDIUM CONTEXT"
    assert coverage["recommended_coverage"] == 0.5
    assert "vendor" in coverage["recommended_fields_present"]
    assert "location" in coverage["recommended_fields_missing"]

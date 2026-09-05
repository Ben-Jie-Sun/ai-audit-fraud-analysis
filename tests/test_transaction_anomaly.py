import pandas as pd

from app.audit.anomaly import (
    build_transaction_features,
    detect_transaction_anomalies,
    evaluate_synthetic_detection,
    summarize_clusters,
)


def _ledger(rows: int = 40) -> pd.DataFrame:
    data = []
    for i in range(rows):
        data.append(
            {
                "transaction_id": f"TX{i:04d}",
                "employee_id": f"EMP{i % 4}",
                "employee_name": f"Employee {i % 4}",
                "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i % 20),
                "vendor": f"Vendor {i % 5}",
                "category": f"Category {i % 3}",
                "amount": 1000.0 + (i % 7) * 25.0,
                "synthetic_anomaly": False,
            }
        )
    data[-1]["amount"] = 100000.0
    data[-1]["synthetic_anomaly"] = True
    return pd.DataFrame(data)


def test_feature_builder_does_not_use_ground_truth_label():
    df = _ledger()
    features = build_transaction_features(df)
    assert "synthetic_anomaly" not in features.columns
    assert len(features) == len(df)


def test_transaction_anomaly_pipeline_adds_analysis_columns():
    result = detect_transaction_anomalies(_ledger())
    for column in (
        "cluster_id",
        "cluster_distance",
        "isolation_score",
        "is_anomaly",
        "anomaly_reason",
    ):
        assert column in result.columns
    assert result["is_anomaly"].dtype == bool


def test_synthetic_evaluation_is_available_when_label_exists():
    result = detect_transaction_anomalies(_ledger())
    evaluation = evaluate_synthetic_detection(result)
    assert evaluation is not None
    assert 0.0 <= evaluation["precision"] <= 1.0
    assert 0.0 <= evaluation["recall"] <= 1.0
    assert 0.0 <= evaluation["f1"] <= 1.0


def test_cluster_summary_covers_all_transactions():
    result = detect_transaction_anomalies(_ledger())
    summary = summarize_clusters(result)
    assert sum(item["transactions"] for item in summary) == len(result)


def test_benchmark_labels_cannot_change_features_or_predictions():
    df = _ledger(80)
    df["anomaly_type"] = "normal"

    changed = df.copy()
    changed["synthetic_anomaly"] = ~changed["synthetic_anomaly"].astype(bool)
    changed["anomaly_type"] = "completely_different_label"

    features_a = build_transaction_features(df)
    features_b = build_transaction_features(changed)
    pd.testing.assert_frame_equal(features_a, features_b)

    result_a = detect_transaction_anomalies(df)
    result_b = detect_transaction_anomalies(changed)
    pd.testing.assert_series_equal(
        result_a["is_anomaly"], result_b["is_anomaly"], check_names=False
    )
    pd.testing.assert_series_equal(
        result_a["cluster_id"], result_b["cluster_id"], check_names=False
    )


def test_detector_does_not_force_a_fixed_two_percent_rate():
    rows = []
    for i in range(200):
        rows.append(
            {
                "transaction_id": f"N{i:04d}",
                "employee_id": f"EMP{i % 10}",
                "employee_name": f"Employee {i % 10}",
                "date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i),
                "vendor": f"Vendor {i % 7}",
                "category": f"Category {i % 4}",
                "amount": 1000.0 + (i % 11) * 20.0,
                "location": f"Location {i % 3}",
                "synthetic_anomaly": False,
            }
        )
    clean = pd.DataFrame(rows)
    risky = clean.copy()
    risky.loc[risky.index[-20:], "amount"] *= 12

    clean_result = detect_transaction_anomalies(clean)
    risky_result = detect_transaction_anomalies(risky)

    assert int(risky_result["is_anomaly"].sum()) > int(clean_result["is_anomaly"].sum())
    assert int(risky_result["is_anomaly"].sum()) != 4  # 2% of 200


def test_pattern_columns_are_explainable_and_present():
    result = detect_transaction_anomalies(_ledger(80))
    expected = {
        "pattern_duplicate_payment",
        "pattern_split_payment",
        "pattern_vendor_burst",
        "pattern_employee_burst",
        "pattern_category_shift",
        "pattern_location_shift",
        "pattern_rounded_repeat",
        "pattern_amount_deviation",
        "pattern_approval_threshold_exceeded",
        "pattern_count",
    }
    assert expected.issubset(result.columns)

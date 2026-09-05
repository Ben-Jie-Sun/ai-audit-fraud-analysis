"""
Statistical, behavioural, and unsupervised anomaly detection.

The single-invoice path remains deliberately simple and auditable: it
compares an invoice amount with the historical median for the category.

The transaction-ledger path is a hybrid fraud-pattern screen. It combines:
  * auditable behavioural features,
  * K-Means behavioural clustering,
  * Isolation Forest anomaly scoring, and
  * explicit pattern signals such as duplicates, split payments, bursts,
    unusual employee/category/location behaviour, and repeated round amounts.

A flagged transaction is suspicious, not proven fraudulent. The system is
intended to prioritize human review, not replace auditor judgement.

IMPORTANT: columns used only as test ground truth (for example
``synthetic_anomaly`` and ``anomaly_type``) are never used as model features.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler

from app.models.schemas import Evidence, ExtractedInvoice, Finding, FindingStatus
from config import ANOMALY_RATIO_THRESHOLD, APPROVAL_THRESHOLD

# Evaluation-only columns are explicitly excluded from inference. This guards
# against label leakage when generated/curated benchmark ledgers are uploaded.
EVALUATION_ONLY_COLUMNS = {
    "synthetic_anomaly",
    "anomaly_type",
    "ground_truth",
    "expected_anomaly",
    "expected_pattern",
}


def load_historical(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except FileNotFoundError:
        return pd.DataFrame(
            columns=["vendor", "invoice_number", "date", "amount", "category"]
        )
    return df


def check_amount_anomaly(invoice: ExtractedInvoice, historical: pd.DataFrame) -> Finding:
    amount = invoice.amount
    category = invoice.category

    if amount is None:
        return Finding(
            id="amount_anomaly",
            title="Amount anomaly",
            status=FindingStatus.WARNING,
            detail="Amount unavailable — could not compare against category history.",
            evidence=[],
            weight=5,
        )

    if historical.empty or not category:
        return Finding(
            id="amount_anomaly",
            title="Amount anomaly",
            status=FindingStatus.PASS,
            detail="No historical category data available to compare against.",
            evidence=[Evidence(label="Invoice amount", value=f"₹{amount:,.2f}")],
            weight=0,
        )

    category_rows = historical[
        historical["category"].str.strip().str.lower() == category.strip().lower()
    ]

    if category_rows.empty:
        return Finding(
            id="amount_anomaly",
            title="Amount anomaly",
            status=FindingStatus.PASS,
            detail=f"No historical transactions found for category '{category}'.",
            evidence=[Evidence(label="Invoice amount", value=f"₹{amount:,.2f}")],
            weight=0,
        )

    median = float(category_rows["amount"].median())
    ratio = amount / median if median > 0 else float("inf")

    if ratio >= ANOMALY_RATIO_THRESHOLD:
        return Finding(
            id="amount_anomaly",
            title="Amount anomaly",
            status=FindingStatus.WARNING,
            detail=(
                f"Amount is {ratio:.1f}x the historical median for category "
                f"'{category}'."
            ),
            evidence=[
                Evidence(label="Invoice amount", value=f"₹{amount:,.2f}"),
                Evidence(label="Category median", value=f"₹{median:,.2f}"),
                Evidence(label="Ratio", value=f"{ratio:.2f}x"),
                Evidence(label="Sample size", value=str(len(category_rows))),
            ],
            weight=20,
        )

    return Finding(
        id="amount_anomaly",
        title="Amount anomaly",
        status=FindingStatus.PASS,
        detail=f"Amount is consistent with historical spend for category '{category}'.",
        evidence=[
            Evidence(label="Invoice amount", value=f"₹{amount:,.2f}"),
            Evidence(label="Category median", value=f"₹{median:,.2f}"),
            Evidence(label="Ratio", value=f"{ratio:.2f}x"),
        ],
        weight=0,
    )


def _safe_share(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.astype(float) / denominator.replace(0, np.nan).astype(float)


def build_transaction_features(transactions: pd.DataFrame) -> pd.DataFrame:
    """Build auditable behavioural features for unsupervised analysis.

    Ground-truth/evaluation columns are deliberately ignored. The same model
    features are therefore produced whether benchmark labels are present,
    absent, or modified.
    """
    if transactions.empty:
        raise ValueError("Transaction dataset is empty.")

    required = {"amount", "employee_id", "date"}
    missing = required - set(transactions.columns)
    if missing:
        raise ValueError(
            "Transaction dataset is missing analysis columns: "
            + ", ".join(sorted(missing))
        )

    # Explicitly remove evaluation-only fields from the inference view.
    result = transactions.drop(
        columns=[c for c in EVALUATION_ONLY_COLUMNS if c in transactions.columns],
        errors="ignore",
    ).copy()
    features = pd.DataFrame(index=result.index)

    amount = pd.to_numeric(result["amount"], errors="coerce").astype(float)
    features["log_amount"] = np.log1p(amount.clip(lower=0))

    employee_median = result.groupby("employee_id")["amount"].transform("median")
    features["employee_amount_ratio"] = amount / employee_median.replace(0, np.nan)

    has_category = "category" in result.columns and result["category"].notna().any()
    has_vendor = "vendor" in result.columns and result["vendor"].notna().any()

    if has_category:
        category_median = result.groupby("category", dropna=False)["amount"].transform("median")
        features["category_amount_ratio"] = amount / category_median.replace(0, np.nan)
    else:
        features["category_amount_ratio"] = 1.0

    if has_vendor:
        vendor_median = result.groupby("vendor", dropna=False)["amount"].transform("median")
        features["vendor_amount_ratio"] = amount / vendor_median.replace(0, np.nan)
    else:
        features["vendor_amount_ratio"] = 1.0

    employee_count = result["employee_id"].map(result["employee_id"].value_counts())
    total = max(len(result), 1)
    features["employee_frequency"] = employee_count / total

    if has_vendor:
        vendor_count = result["vendor"].map(result["vendor"].value_counts())
        features["vendor_frequency"] = vendor_count / total
        employee_vendor_count = result.groupby(
            ["employee_id", "vendor"], dropna=False
        )["amount"].transform("size")
        features["employee_vendor_share"] = _safe_share(
            employee_vendor_count, employee_count
        )
    else:
        features["vendor_frequency"] = 0.0
        features["employee_vendor_share"] = 0.0

    if has_category:
        category_count = result["category"].map(result["category"].value_counts())
        features["category_frequency"] = category_count / total
        employee_category_count = result.groupby(
            ["employee_id", "category"], dropna=False
        )["amount"].transform("size")
        features["employee_category_share"] = _safe_share(
            employee_category_count, employee_count
        )
    else:
        features["category_frequency"] = 0.0
        features["employee_category_share"] = 0.0

    dates = pd.to_datetime(result["date"], errors="coerce")
    features["day_of_week"] = dates.dt.dayofweek.astype(float)
    features["day_of_month"] = dates.dt.day.astype(float)

    date_key = dates.dt.normalize()
    temp = result.assign(_audit_date=date_key)
    employee_daily_count = temp.groupby(
        ["employee_id", "_audit_date"], dropna=False
    )["amount"].transform("size")
    features["employee_daily_count"] = employee_daily_count.astype(float)
    if has_vendor:
        employee_vendor_daily_count = temp.groupby(
            ["employee_id", "vendor", "_audit_date"], dropna=False
        )["amount"].transform("size")
        features["employee_vendor_daily_count"] = employee_vendor_daily_count.astype(float)
    else:
        features["employee_vendor_daily_count"] = 0.0

    # Past-only behavioural shares: for each row, measure what was normal for
    # that employee *before* the transaction date. This is more robust than
    # profiling a behaviour from the same batch that may already contain a
    # coordinated shift.
    ordered = temp.sort_values(["_audit_date", "employee_id"], kind="stable").copy()
    ordered["_prior_employee_count"] = ordered.groupby("employee_id").cumcount()
    if has_category:
        ordered["_prior_category_count"] = ordered.groupby(
            ["employee_id", "category"], dropna=False
        ).cumcount()
    else:
        ordered["_prior_category_count"] = ordered["_prior_employee_count"]
    if "location" in ordered.columns and ordered["location"].notna().any():
        ordered["_prior_location_count"] = ordered.groupby(
            ["employee_id", "location"], dropna=False
        ).cumcount()
    else:
        ordered["_prior_location_count"] = ordered["_prior_employee_count"]

    prior_count = ordered["_prior_employee_count"].replace(0, np.nan)
    ordered["_historical_category_share"] = (
        ordered["_prior_category_count"] / prior_count
    ).fillna(1.0)
    ordered["_historical_location_share"] = (
        ordered["_prior_location_count"] / prior_count
    ).fillna(1.0)

    features["employee_prior_count"] = ordered["_prior_employee_count"].reindex(result.index).astype(float)
    features["historical_category_share"] = ordered["_historical_category_share"].reindex(result.index).astype(float)
    features["historical_location_share"] = ordered["_historical_location_share"].reindex(result.index).astype(float)

    duplicate_group = ["employee_id", "_audit_date", "amount"]
    if has_vendor:
        duplicate_group.insert(1, "vendor")
    exact_duplicate_size = temp.groupby(
        duplicate_group, dropna=False
    )["amount"].transform("size")
    features["exact_duplicate_size"] = exact_duplicate_size.astype(float)

    if has_vendor:
        same_day_vendor_total = temp.groupby(
            ["employee_id", "vendor", "_audit_date"], dropna=False
        )["amount"].transform("sum")
        features["same_day_vendor_total_ratio"] = (
            same_day_vendor_total.astype(float) / max(float(APPROVAL_THRESHOLD), 1.0)
        )
    else:
        features["same_day_vendor_total_ratio"] = 0.0

    # Repeated values close to common approval-avoidance amounts (e.g. 49,999
    # or 99,999) are not proof of wrongdoing, but they are useful review cues.
    rounded_1000 = (amount / 1000.0).round() * 1000.0
    round_distance = (amount - rounded_1000).abs()
    features["round_amount_closeness"] = 1.0 - (round_distance / 1000.0).clip(0, 1)
    rounded_group = ["employee_id", "_rounded_1000"]
    if has_vendor:
        rounded_group.insert(1, "vendor")
    rounded_repeat = temp.assign(_rounded_1000=rounded_1000).groupby(
        rounded_group, dropna=False
    )["amount"].transform("size")
    features["rounded_repeat_size"] = rounded_repeat.astype(float)

    if "location" in result.columns and result["location"].notna().any():
        employee_location_count = result.groupby(
            ["employee_id", "location"], dropna=False
        )["amount"].transform("size")
        features["employee_location_share"] = _safe_share(
            employee_location_count, employee_count
        )
    else:
        features["employee_location_share"] = 1.0

    if "payment_method" in result.columns:
        employee_payment_count = result.groupby(
            ["employee_id", "payment_method"], dropna=False
        )["amount"].transform("size")
        features["employee_payment_share"] = _safe_share(
            employee_payment_count, employee_count
        )
    else:
        features["employee_payment_share"] = 1.0

    return features.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _robust_upper_threshold(values: np.ndarray, z: float = 4.0) -> float:
    """Return a robust high-outlier threshold based on median absolute deviation."""
    values = np.asarray(values, dtype=float)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        return float(np.max(values)) if len(values) else 0.0
    robust_sigma = 1.4826 * mad
    return median + z * robust_sigma


def _pattern_signals(
    transactions: pd.DataFrame,
    features: pd.DataFrame,
) -> dict[str, np.ndarray]:
    """Return explicit, human-auditable fraud-pattern screening signals."""
    result = transactions.copy()
    dates = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    temp = result.assign(_audit_date=dates)

    employee_count = result["employee_id"].map(result["employee_id"].value_counts())

    duplicate = features["exact_duplicate_size"].ge(2).to_numpy()

    has_vendor = "vendor" in result.columns and result["vendor"].notna().any()
    has_category = "category" in result.columns and result["category"].notna().any()

    if has_vendor:
        same_day_group_count = temp.groupby(
            ["employee_id", "vendor", "_audit_date"], dropna=False
        )["amount"].transform("size")
        same_day_group_total = temp.groupby(
            ["employee_id", "vendor", "_audit_date"], dropna=False
        )["amount"].transform("sum")
        split_payment = (
            same_day_group_count.ge(3)
            & same_day_group_total.ge(APPROVAL_THRESHOLD)
            & pd.to_numeric(result["amount"], errors="coerce").lt(APPROVAL_THRESHOLD)
        ).to_numpy()
        vendor_burst = features["employee_vendor_daily_count"].ge(4).to_numpy()
    else:
        split_payment = np.zeros(len(result), dtype=bool)
        vendor_burst = np.zeros(len(result), dtype=bool)

    employee_burst = features["employee_daily_count"].ge(6).to_numpy()

    if has_category:
        category_shift = (
            features["employee_prior_count"].ge(8)
            & features["historical_category_share"].le(0.08)
            & features["employee_amount_ratio"].ge(1.4)
        ).to_numpy()
    else:
        category_shift = np.zeros(len(result), dtype=bool)

    if "location" in result.columns and result["location"].notna().any():
        location_shift = (
            features["employee_prior_count"].ge(8)
            & features["historical_location_share"].le(0.08)
            & features["employee_amount_ratio"].ge(1.25)
        ).to_numpy()
    else:
        location_shift = np.zeros(len(result), dtype=bool)

    rounded_repeat = (
        features["rounded_repeat_size"].ge(3)
        & features["round_amount_closeness"].ge(0.95)
    ).to_numpy()

    amount_deviation_series = features["employee_amount_ratio"].ge(3.5)
    if has_category:
        amount_deviation_series = amount_deviation_series | features["category_amount_ratio"].ge(3.5)
    if has_vendor:
        amount_deviation_series = amount_deviation_series | features["vendor_amount_ratio"].ge(4.5)
    amount_deviation = amount_deviation_series.to_numpy()

    # Policy / control threshold: unlike clustering and within-batch statistics,
    # this is an external audit reference point. It remains meaningful even if
    # a large fraction of the uploaded ledger is abnormal. Exceeding it does
    # not prove fraud; it means the transaction needs additional review.
    approval_threshold_exceeded = (
        pd.to_numeric(result["amount"], errors="coerce") >= APPROVAL_THRESHOLD
    ).fillna(False).to_numpy()

    return {
        "duplicate_payment": duplicate,
        "split_payment": split_payment,
        "vendor_burst": vendor_burst,
        "employee_burst": employee_burst,
        "category_shift": category_shift,
        "location_shift": location_shift,
        "rounded_repeat": rounded_repeat,
        "amount_deviation": amount_deviation,
        "approval_threshold_exceeded": approval_threshold_exceeded,
    }


def detect_transaction_anomalies(transactions: pd.DataFrame) -> pd.DataFrame:
    """Run hybrid multivariate clustering + anomaly screening.

    ``cluster_distance`` measures distance from the assigned behavioural
    cluster centre in standardized feature space. Larger values indicate a
    transaction is less typical of its cluster.

    ``isolation_score`` is the inverted Isolation Forest sample score. Larger
    values indicate that the transaction is easier to isolate from the rest of
    the ledger. Neither value is a fraud probability.
    """
    if len(transactions) < 2:
        raise ValueError("At least two transactions are required for pattern analysis.")

    result = transactions.copy()
    feature_df = build_transaction_features(result)

    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(feature_df)

    n_clusters = min(6, max(2, int(round(math.sqrt(len(result) / 250)) + 2)))
    n_clusters = min(n_clusters, len(result))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_ids = kmeans.fit_predict(scaled_features)
    centers = kmeans.cluster_centers_[cluster_ids]
    distances = np.linalg.norm(scaled_features - centers, axis=1)

    isolation = IsolationForest(
        contamination="auto",
        random_state=42,
        n_estimators=250,
    )
    isolation.fit(scaled_features)
    isolation_scores = -isolation.score_samples(scaled_features)

    isolation_threshold = _robust_upper_threshold(isolation_scores, z=4.25)
    isolation_outlier = isolation_scores > isolation_threshold

    cluster_outlier = np.zeros(len(result), dtype=bool)
    for cluster_id in np.unique(cluster_ids):
        mask = cluster_ids == cluster_id
        threshold = _robust_upper_threshold(distances[mask], z=4.25)
        cluster_outlier[mask] = distances[mask] > threshold

    signals = _pattern_signals(result, feature_df)
    explicit_pattern_count = np.zeros(len(result), dtype=int)
    for flag in signals.values():
        explicit_pattern_count += flag.astype(int)

    # Strong explicit signals are actionable on their own. Subtler behavioural
    # cases require agreement between ML signals or multiple explicit cues.
    strong_pattern = (
        signals["duplicate_payment"]
        | signals["split_payment"]
        | signals["vendor_burst"]
        | signals["amount_deviation"]
        | signals["approval_threshold_exceeded"]
    )
    ml_agreement = isolation_outlier & cluster_outlier
    soft_profile_shift = (signals["category_shift"] | signals["location_shift"]) & (
        isolation_outlier | cluster_outlier | signals["amount_deviation"]
    )
    mixed_evidence = (explicit_pattern_count >= 2) & (
        isolation_outlier | cluster_outlier
    )
    is_anomaly = strong_pattern | ml_agreement | soft_profile_shift | mixed_evidence

    reasons: list[str] = []
    pattern_names = list(signals.keys())
    for row_index in range(len(result)):
        active = [
            name.replace("_", " ")
            for name in pattern_names
            if bool(signals[name][row_index])
        ]
        if ml_agreement[row_index]:
            active.append("Isolation Forest + cluster deviation")
        elif isolation_outlier[row_index]:
            active.append("Isolation Forest deviation")
        elif cluster_outlier[row_index]:
            active.append("cluster-distance deviation")

        if is_anomaly[row_index] and active:
            reasons.append("; ".join(active))
        elif is_anomaly[row_index]:
            reasons.append("Unusual multivariate transaction behaviour")
        else:
            reasons.append("Consistent with learned transaction patterns")

    result["cluster_id"] = cluster_ids.astype(int)
    result["cluster_distance"] = distances.astype(float)
    result["isolation_score"] = isolation_scores.astype(float)
    result["isolation_outlier"] = isolation_outlier.astype(bool)
    result["cluster_outlier"] = cluster_outlier.astype(bool)

    for name, flag in signals.items():
        result[f"pattern_{name}"] = flag.astype(bool)

    result["pattern_count"] = explicit_pattern_count.astype(int)
    result["is_anomaly"] = is_anomaly.astype(bool)
    result["anomaly_reason"] = reasons
    return result


def evaluate_synthetic_detection(transactions: pd.DataFrame) -> dict | None:
    """Evaluate predictions only when benchmark ground truth is available.

    These labels are never part of feature engineering. They are read only
    after predictions exist, exactly like labels in a held-out benchmark.
    """
    if "synthetic_anomaly" not in transactions.columns:
        return None
    if "is_anomaly" not in transactions.columns:
        raise ValueError("Predictions are required before evaluation.")

    truth = transactions["synthetic_anomaly"].astype(bool)
    predicted = transactions["is_anomaly"].astype(bool)

    tp = int((truth & predicted).sum())
    fp = int((~truth & predicted).sum())
    fn = int((truth & ~predicted).sum())
    tn = int((~truth & ~predicted).sum())

    precision, recall, f1, _ = precision_recall_fscore_support(
        truth,
        predicted,
        average="binary",
        zero_division=0,
    )

    evaluation: dict = {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
    }

    if "anomaly_type" in transactions.columns:
        by_pattern: list[dict] = []
        labels = transactions["anomaly_type"].fillna("normal").astype(str)
        for pattern in sorted(p for p in labels.unique() if p != "normal"):
            mask = labels.eq(pattern)
            injected = int(mask.sum())
            detected = int((mask & predicted).sum())
            by_pattern.append(
                {
                    "pattern": pattern,
                    "injected": injected,
                    "detected": detected,
                    "recall": detected / injected if injected else 0.0,
                }
            )
        evaluation["by_pattern"] = by_pattern

    return evaluation


def summarize_clusters(transactions: pd.DataFrame) -> list[dict]:
    """Return compact, UI-friendly statistics for each behavioural cluster."""
    if "cluster_id" not in transactions.columns:
        return []

    summary: list[dict] = []
    for cluster_id, rows in transactions.groupby("cluster_id"):
        dominant_category = (
            rows["category"].mode().iloc[0]
            if "category" in rows.columns and not rows["category"].mode().empty
            else "n/a"
        )
        dominant_department = (
            rows["department"].mode().iloc[0]
            if "department" in rows.columns and not rows["department"].mode().empty
            else "n/a"
        )
        summary.append(
            {
                "cluster_id": int(cluster_id),
                "transactions": int(len(rows)),
                "average_amount": float(rows["amount"].mean()),
                "median_amount": float(rows["amount"].median()),
                "anomalies": int(rows["is_anomaly"].sum()),
                "anomaly_rate": float(rows["is_anomaly"].mean()),
                "dominant_category": str(dominant_category),
                "dominant_department": str(dominant_department),
            }
        )
    return summary

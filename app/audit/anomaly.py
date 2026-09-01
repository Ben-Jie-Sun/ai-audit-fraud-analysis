"""
Statistical anomaly detection.

This is deliberately simple and auditable: compare the transaction
amount to the historical median for the same category, and flag it if
the ratio exceeds a configured threshold. No black-box model — just a
ratio anyone can recompute from the same historical data.
"""

from __future__ import annotations

import pandas as pd

from app.models.schemas import Evidence, ExtractedInvoice, Finding, FindingStatus
from config import ANOMALY_RATIO_THRESHOLD


def load_historical(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except FileNotFoundError:
        return pd.DataFrame(columns=["vendor", "invoice_number", "date", "amount", "category"])
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

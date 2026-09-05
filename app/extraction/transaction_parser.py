"""
Transaction ledger parsing and validation.

Pipeline:

    CSV / Excel
        ↓
    pandas DataFrame
        ↓
    validate required columns
        ↓
    normalize values
        ↓
    trusted transaction data

Unlike document_parser.py, this module handles a ledger containing
many transactions rather than extracting one invoice.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Transaction schema requirements
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "transaction_id",
    "employee_id",
    "employee_name",
    "date",
    "vendor",
    "category",
    "amount",
}


def load_transaction_file(file_path: str) -> pd.DataFrame:
    """
    Load a CSV or Excel transaction ledger.

    The returned DataFrame has already been validated and normalized.
    """

    path = Path(file_path)

    extension = path.suffix.lower()

    if extension == ".csv":
        df = pd.read_csv(path)

    elif extension == ".xlsx":
        df = pd.read_excel(path)

    else:
        raise ValueError(
            "Unsupported transaction file. Use CSV or XLSX."
        )

    validate_transaction_dataframe(df)

    df = normalize_transaction_dataframe(df)

    return df


def validate_transaction_dataframe(df: pd.DataFrame) -> None:
    """
    Check whether the uploaded ledger contains the fields
    required by the fraud-analysis pipeline.
    """

    if df.empty:
        raise ValueError(
            "The uploaded transaction file contains no rows."
        )

    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        missing_list = ", ".join(
            sorted(missing_columns)
        )

        raise ValueError(
            f"Missing required columns: {missing_list}"
        )


def normalize_transaction_dataframe(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Convert important columns into predictable data types.
    """

    df = df.copy()

    # Convert amounts such as:
    #
    # 10000
    # "10000"
    #
    # into numeric values.

    df["amount"] = pd.to_numeric(
        df["amount"],
        errors="coerce",
    )

    # Convert supported date representations into
    # pandas datetime values.

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    # If conversion failed, NaN/NaT will appear.

    if df["amount"].isna().any():
        raise ValueError(
            "Some transaction amounts are invalid."
        )

    if df["date"].isna().any():
        raise ValueError(
            "Some transaction dates are invalid."
        )

    return df
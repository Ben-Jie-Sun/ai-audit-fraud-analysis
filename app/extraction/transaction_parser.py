"""Flexible transaction-ledger parsing, schema mapping and normalization.

External spreadsheets do not need to use the project's exact internal column
names.  This module maps common aliases and small spelling variations to a
canonical schema, then validates only the core fields that are genuinely
required for analysis.

Pipeline::

    CSV / Excel
        -> column-name normalization / fuzzy schema mapping
        -> canonical transaction schema
        -> core validation
        -> value normalization
        -> trusted DataFrame + mapping/coverage metadata

Optional fields such as vendor, category and location are intentionally not
required.  Downstream fraud signals that depend on unavailable fields are
skipped rather than invented.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re

import pandas as pd


# Minimum schema required to run transaction-level ML safely.  The audit
# engine needs a stable row identifier, a time reference, a numeric amount,
# and at least one employee identity field (employee_id OR employee_name).
CORE_REQUIRED_COLUMNS = {"transaction_id", "amount", "date"}
EMPLOYEE_IDENTITY_COLUMNS = {"employee_id", "employee_name"}

# These fields are not mandatory, but materially strengthen context-specific
# fraud checks and reviewer routing. Missing fields disable only the dependent
# signals; the remaining analysis still runs.
RECOMMENDED_CONTEXT_FIELDS = [
    "vendor",
    "category",
    "location",
    "department",
    "manager_name",
    "payment_method",
]

OPTIONAL_CONTEXT_FIELDS = ["description"]

CANONICAL_ALIASES: dict[str, set[str]] = {
    "transaction_id": {
        "transaction_id", "transaction id", "txn_id", "txn id", "tx_id",
        "payment_id", "payment id", "reference_id", "reference id",
        "transaction_number", "transaction no", "transaction_no",
    },
    "employee_id": {
        "employee_id", "employee id", "emp_id", "emp id", "staff_id",
        "staff id", "user_id", "user id", "submitter_id", "submitter id",
        "account_id", "account id",
    },
    "employee_name": {
        "employee_name", "employee name", "employee", "staff_name",
        "staff name", "submitter", "submitter_name", "submitter name",
        "user_name", "user name",
    },
    "date": {
        "date", "transaction_date", "transaction date", "txn_date",
        "payment_date", "payment date", "expense_date", "expense date",
        "posting_date", "posting date", "created_at", "created at",
    },
    "vendor": {
        "vendor", "vendor_name", "vendor name", "merchant", "merchant_name",
        "merchant name", "seller", "supplier", "supplier_name",
        "supplier name", "payee", "counterparty", "counter_party",
    },
    "category": {
        "category", "expense_category", "expense category", "type",
        "expense_type", "expense type", "transaction_type", "transaction type",
        "spend_category", "spend category",
    },
    "amount": {
        "amount", "transaction_amount", "transaction amount", "value",
        "payment_amount", "payment amount", "expense_amount", "expense amount",
        "total_amount", "total amount", "net_amount", "net amount",
    },
    "manager_name": {
        "manager_name", "manager name", "manager", "supervisor",
        "supervisor_name", "supervisor name", "approver", "approver_name",
    },
    "department": {
        "department", "dept", "business_unit", "business unit", "division",
        "cost_center", "cost center",
    },
    "payment_method": {
        "payment_method", "payment method", "method", "payment_mode",
        "payment mode", "mode", "channel",
    },
    "location": {
        "location", "city", "office_location", "office location", "region",
        "place", "branch", "branch_location", "branch location",
    },
    "description": {
        "description", "details", "narration", "memo", "remarks", "notes",
        "purpose", "business_purpose", "business purpose",
    },
}


def _normalise_header(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in CANONICAL_ALIASES.items():
        index[_normalise_header(canonical)] = canonical
        for alias in aliases:
            index[_normalise_header(alias)] = canonical
    return index


_ALIAS_INDEX = _alias_index()


def _best_fuzzy_mapping(header: str) -> tuple[str | None, float]:
    """Return a canonical field and confidence for a misspelled header.

    We deliberately use a conservative threshold.  Low-confidence guesses are
    left unmapped so the user sees a clear validation/coverage message instead
    of a silent semantic mistake.
    """
    normalised = _normalise_header(header)
    best_canonical: str | None = None
    best_score = 0.0
    second_score = 0.0

    for alias, canonical in _ALIAS_INDEX.items():
        score = SequenceMatcher(None, normalised, alias).ratio()
        if score > best_score:
            second_score = best_score
            best_score = score
            best_canonical = canonical
        elif score > second_score:
            second_score = score

    # Require both decent similarity and a margin over the runner-up to avoid
    # silently mapping ambiguous names such as "type" to the wrong concept.
    if best_score >= 0.78 and (best_score - second_score >= 0.04 or best_score >= 0.92):
        return best_canonical, best_score
    return None, best_score


def map_transaction_schema(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Map arbitrary-ish spreadsheet headers to the canonical audit schema."""
    mapped = df.copy()
    used_canonical: set[str] = set()
    rename_map: dict[object, str] = {}
    mapping_report: list[dict] = []

    for original in df.columns:
        normalised = _normalise_header(original)
        canonical = _ALIAS_INDEX.get(normalised)
        method = "exact/alias"
        confidence = 1.0

        if canonical is None:
            canonical, confidence = _best_fuzzy_mapping(str(original))
            method = "fuzzy" if canonical else "unmapped"

        if canonical and canonical not in used_canonical:
            rename_map[original] = canonical
            used_canonical.add(canonical)
            mapping_report.append(
                {
                    "original_column": str(original),
                    "canonical_column": canonical,
                    "method": method,
                    "confidence": round(float(confidence), 3),
                }
            )
        else:
            # Preserve unknown/duplicate semantic columns under a normalized
            # name; they remain available in the output but are not fed into
            # audit logic unless explicitly supported.
            fallback = normalised or f"column_{len(mapping_report) + 1}"
            if fallback in mapped.columns or fallback in used_canonical:
                fallback = f"raw_{fallback}"
            rename_map[original] = fallback
            mapping_report.append(
                {
                    "original_column": str(original),
                    "canonical_column": None,
                    "method": "unmapped" if canonical is None else "duplicate_mapping",
                    "confidence": round(float(confidence), 3),
                }
            )

    mapped = mapped.rename(columns=rename_map)
    return mapped, mapping_report


def _ensure_identity_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, bool]]:
    result = df.copy()
    availability = {
        "employee_identity": bool(
            ("employee_id" in result.columns and result["employee_id"].notna().any())
            or ("employee_name" in result.columns and result["employee_name"].notna().any())
        ),
        "vendor": "vendor" in result.columns and result["vendor"].notna().any(),
        "category": "category" in result.columns and result["category"].notna().any(),
        "location": "location" in result.columns and result["location"].notna().any(),
        "department": "department" in result.columns and result["department"].notna().any(),
        "payment_method": "payment_method" in result.columns and result["payment_method"].notna().any(),
        "manager_name": "manager_name" in result.columns and result["manager_name"].notna().any(),
    }

    if "employee_id" not in result.columns:
        if "employee_name" in result.columns:
            names = result["employee_name"].fillna("Unknown").astype(str)
            codes, _ = pd.factorize(names, sort=True)
            result["employee_id"] = [f"AUTO-EMP-{code + 1:05d}" for code in codes]
        else:
            # Unique per-row pseudo IDs deliberately disable employee-history
            # aggregation rather than pretending all unknown rows are one user.
            result["employee_id"] = [f"UNKNOWN-ENTITY-{i + 1:06d}" for i in range(len(result))]

    if "employee_name" not in result.columns:
        result["employee_name"] = result["employee_id"].astype(str)

    return result, availability


def _coverage_metadata(availability: dict[str, bool]) -> dict:
    enabled: list[str] = ["amount deviation", "global anomaly", "behavioural clustering"]
    skipped: list[str] = []

    if availability["employee_identity"]:
        enabled += ["employee spending profile", "employee burst"]
    else:
        skipped += ["employee spending profile", "employee burst"]

    if availability["vendor"]:
        enabled += ["vendor frequency", "vendor burst", "split payment", "employee-vendor patterns"]
    else:
        skipped += ["vendor frequency", "vendor burst", "split payment", "employee-vendor patterns"]

    if availability["category"]:
        enabled += ["category deviation", "category shift"]
    else:
        skipped += ["category deviation", "category shift"]

    if availability["location"]:
        enabled.append("location shift")
    else:
        skipped.append("location shift")

    if availability["department"]:
        enabled.append("department context (reporting)")
    else:
        skipped.append("department context")

    recommended_present = [
        field for field in RECOMMENDED_CONTEXT_FIELDS
        if availability.get(field if field != "manager_name" else "manager_name", False)
    ]
    recommended_missing = [
        field for field in RECOMMENDED_CONTEXT_FIELDS
        if field not in recommended_present
    ]
    recommended_coverage = (
        len(recommended_present) / len(RECOMMENDED_CONTEXT_FIELDS)
        if RECOMMENDED_CONTEXT_FIELDS else 1.0
    )

    if recommended_coverage >= 0.999:
        schema_tier = "FULL CONTEXT"
    elif recommended_coverage >= 0.50:
        schema_tier = "MEDIUM CONTEXT"
    else:
        schema_tier = "MINIMUM CONTEXT"

    return {
        "minimum_requirement": [
            "transaction_id",
            "date",
            "amount",
            "employee_id OR employee_name",
        ],
        "recommended_fields": list(RECOMMENDED_CONTEXT_FIELDS),
        "optional_fields": list(OPTIONAL_CONTEXT_FIELDS),
        "available_fields": [name for name, present in availability.items() if present],
        "missing_optional_fields": [name for name, present in availability.items() if not present],
        "recommended_fields_present": recommended_present,
        "recommended_fields_missing": recommended_missing,
        "recommended_coverage": round(float(recommended_coverage), 4),
        "schema_tier": schema_tier,
        "enabled_signals": enabled,
        "skipped_signals": skipped,
    }


def load_transaction_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".csv":
        raw_df = pd.read_csv(path)
    elif extension == ".xlsx":
        raw_df = pd.read_excel(path)
    else:
        raise ValueError("Unsupported transaction file. Use CSV or XLSX.")

    if raw_df.empty:
        raise ValueError("The uploaded transaction file contains no rows.")

    df, mapping_report = map_transaction_schema(raw_df)
    validate_transaction_dataframe(df)
    df, availability = _ensure_identity_columns(df)
    df = normalize_transaction_dataframe(df)

    df.attrs["schema_mapping"] = mapping_report
    df.attrs["data_coverage"] = _coverage_metadata(availability)
    return df


def validate_transaction_dataframe(df: pd.DataFrame) -> None:
    """Validate the minimum schema needed for meaningful transaction ML.

    Minimum requirement:
      * transaction_id
      * date
      * amount
      * employee_id OR employee_name

    Vendor/category/location/etc. are recommended context, not hard
    requirements. Their dependent signals are skipped when unavailable.
    """
    if df.empty:
        raise ValueError("The uploaded transaction file contains no rows.")

    missing = CORE_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            "Could not identify minimum required transaction fields: "
            + ", ".join(sorted(missing))
            + ". Minimum schema: Transaction ID, Date, Amount, and Employee ID "
            "or Employee Name. Download the minimum Excel template from the UI "
            "or rename the relevant columns; common aliases and small spelling "
            "mistakes are auto-recognized."
        )

    has_employee_id = "employee_id" in df.columns and df["employee_id"].notna().any()
    has_employee_name = "employee_name" in df.columns and df["employee_name"].notna().any()
    if not (has_employee_id or has_employee_name):
        raise ValueError(
            "Could not identify an employee identity column. Provide Employee ID "
            "or Employee Name (aliases and small spelling mistakes are accepted)."
        )

    transaction_ids = df["transaction_id"].astype("string").str.strip()
    if transaction_ids.isna().any() or transaction_ids.eq("").any():
        raise ValueError("Every transaction row must contain a Transaction ID.")

    employee_id = (
        df["employee_id"].astype("string").str.strip()
        if "employee_id" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="string")
    )
    employee_name = (
        df["employee_name"].astype("string").str.strip()
        if "employee_name" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="string")
    )
    missing_identity = (
        (employee_id.isna() | employee_id.eq(""))
        & (employee_name.isna() | employee_name.eq(""))
    )
    if missing_identity.any():
        raise ValueError(
            f"{int(missing_identity.sum())} row(s) have neither Employee ID nor Employee Name."
        )


def normalize_transaction_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    # Accept common finance formatting such as ₹10,000 or 10,000.50.
    amount_text = (
        result["amount"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.strip()
    )
    result["amount"] = pd.to_numeric(amount_text, errors="coerce")
    result["date"] = pd.to_datetime(result["date"], errors="coerce")

    if result["amount"].isna().any():
        bad_rows = int(result["amount"].isna().sum())
        raise ValueError(f"{bad_rows} transaction amount(s) are missing or invalid.")

    if result["date"].isna().any():
        bad_rows = int(result["date"].isna().sum())
        raise ValueError(f"{bad_rows} transaction date(s) are missing or invalid.")

    # Normalize text fields without manufacturing optional columns.
    for column in [
        "transaction_id", "employee_id", "employee_name", "vendor", "category",
        "manager_name", "department", "payment_method", "location", "description",
    ]:
        if column in result.columns:
            result[column] = result[column].astype("string").str.strip()

    return result

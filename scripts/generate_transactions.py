from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


EMPLOYEES = {
    "EMP001": {"name": "Aarav", "manager": "Manager A", "department": "Finance", "location": "Mumbai"},
    "EMP002": {"name": "Meera", "manager": "Manager A", "department": "Finance", "location": "Mumbai"},
    "EMP003": {"name": "Kabir", "manager": "Manager B", "department": "Engineering", "location": "Bengaluru"},
    "EMP004": {"name": "Ishita", "manager": "Manager B", "department": "Engineering", "location": "Bengaluru"},
    "EMP005": {"name": "Rohan", "manager": "Manager C", "department": "Operations", "location": "Delhi"},
    "EMP006": {"name": "Ananya", "manager": "Manager C", "department": "Operations", "location": "Delhi"},
    "EMP007": {"name": "Vihaan", "manager": "Manager D", "department": "Sales", "location": "Varanasi"},
    "EMP008": {"name": "Diya", "manager": "Manager D", "department": "Sales", "location": "Varanasi"},
    "EMP009": {"name": "Arjun", "manager": "Manager E", "department": "HR", "location": "Delhi"},
    "EMP010": {"name": "Sara", "manager": "Manager E", "department": "HR", "location": "Mumbai"},
}

VENDORS_BY_CATEGORY = {
    "Office": ["OfficeMart", "PaperPoint", "WorkspaceCo"],
    "Software": ["CloudWorks", "SoftServe", "DataStack"],
    "Travel": ["TravelDesk", "FlyRight", "HotelHub"],
    "Equipment": ["EquipHub", "TechSupply", "MachineMart"],
}

CATEGORY_BASE_AMOUNT = {
    "Office": 8_000,
    "Software": 24_000,
    "Travel": 16_000,
    "Equipment": 32_000,
}

DEPARTMENT_CATEGORY_WEIGHTS = {
    "Finance": [0.45, 0.35, 0.15, 0.05],
    "Engineering": [0.10, 0.45, 0.05, 0.40],
    "Operations": [0.30, 0.10, 0.20, 0.40],
    "Sales": [0.20, 0.10, 0.60, 0.10],
    "HR": [0.55, 0.15, 0.25, 0.05],
}

CATEGORIES = list(VENDORS_BY_CATEGORY)
LOCATIONS = ["Mumbai", "Delhi", "Bengaluru", "Varanasi"]
PAYMENT_METHODS = ["Card", "Bank Transfer", "UPI"]


def _normal_ledger(rows: int, seed: int) -> tuple[pd.DataFrame, np.random.Generator]:
    rng = np.random.default_rng(seed)
    employee_ids = list(EMPLOYEES)
    records: list[dict] = []

    for i in range(rows):
        employee_id = str(rng.choice(employee_ids))
        employee = EMPLOYEES[employee_id]
        category = str(
            rng.choice(
                CATEGORIES,
                p=DEPARTMENT_CATEGORY_WEIGHTS[employee["department"]],
            )
        )
        vendor = str(rng.choice(VENDORS_BY_CATEGORY[category]))
        base_amount = CATEGORY_BASE_AMOUNT[category]
        employee_factor = 0.85 + (employee_ids.index(employee_id) % 5) * 0.07
        amount = max(200.0, rng.normal(base_amount * employee_factor, base_amount * 0.22))

        # Most transactions occur at the employee's normal location.
        if rng.random() < 0.93:
            location = employee["location"]
        else:
            location = str(rng.choice(LOCATIONS))

        records.append(
            {
                "transaction_id": f"TX{i + 1:06d}",
                "employee_id": employee_id,
                "employee_name": employee["name"],
                "date": pd.Timestamp("2026-01-01")
                + pd.Timedelta(days=int(rng.integers(0, 240))),
                "vendor": vendor,
                "category": category,
                "amount": round(float(amount), 2),
                "manager_name": employee["manager"],
                "department": employee["department"],
                "payment_method": str(rng.choice(PAYMENT_METHODS, p=[0.45, 0.40, 0.15])),
                "location": location,
                "synthetic_anomaly": False,
                "anomaly_type": "normal",
            }
        )

    return pd.DataFrame(records), rng


def _mark(df: pd.DataFrame, indexes: list[int] | np.ndarray, pattern: str) -> None:
    df.loc[indexes, "synthetic_anomaly"] = True
    df.loc[indexes, "anomaly_type"] = pattern


def _inject_extreme_amount(df: pd.DataFrame, rng: np.random.Generator, indexes: list[int]) -> None:
    for idx in indexes:
        df.loc[idx, "amount"] = round(float(df.loc[idx, "amount"] * rng.uniform(7, 12)), 2)
    _mark(df, indexes, "extreme_amount")


def _inject_moderate_amount(df: pd.DataFrame, rng: np.random.Generator, indexes: list[int]) -> None:
    for idx in indexes:
        df.loc[idx, "amount"] = round(float(df.loc[idx, "amount"] * rng.uniform(2.6, 3.4)), 2)
    _mark(df, indexes, "moderate_amount")


def _inject_duplicate_payment(df: pd.DataFrame, indexes: list[int]) -> None:
    involved: set[int] = set(indexes)
    for idx in indexes:
        source = max(0, idx - 1)
        involved.add(source)
        for col in ["employee_id", "employee_name", "date", "vendor", "category", "amount", "manager_name", "department", "payment_method", "location"]:
            df.loc[idx, col] = df.loc[source, col]
    _mark(df, sorted(involved), "duplicate_payment")


def _inject_split_payment(df: pd.DataFrame, indexes: list[int]) -> None:
    # Work in groups of three: each payment stays below the approval threshold,
    # but the same-day same-vendor total exceeds it.
    for start in range(0, len(indexes), 3):
        group = indexes[start:start + 3]
        if len(group) < 3:
            break
        employee_id = "EMP003"
        employee = EMPLOYEES[employee_id]
        date = pd.Timestamp("2026-08-15") + pd.Timedelta(days=start // 3)
        for idx, amount in zip(group, [49_000.0, 48_500.0, 47_500.0]):
            df.loc[idx, ["employee_id", "employee_name", "manager_name", "department", "location"]] = [
                employee_id, employee["name"], employee["manager"], employee["department"], employee["location"]
            ]
            df.loc[idx, "date"] = date
            df.loc[idx, "vendor"] = "TechSupply"
            df.loc[idx, "category"] = "Equipment"
            df.loc[idx, "amount"] = amount
    _mark(df, indexes[: (len(indexes) // 3) * 3], "split_payment")


def _inject_vendor_burst(df: pd.DataFrame, indexes: list[int]) -> None:
    for start in range(0, len(indexes), 4):
        group = indexes[start:start + 4]
        if len(group) < 4:
            break
        employee_id = "EMP005"
        employee = EMPLOYEES[employee_id]
        date = pd.Timestamp("2026-07-21") + pd.Timedelta(days=start // 4)
        for j, idx in enumerate(group):
            df.loc[idx, ["employee_id", "employee_name", "manager_name", "department", "location"]] = [
                employee_id, employee["name"], employee["manager"], employee["department"], employee["location"]
            ]
            df.loc[idx, "date"] = date
            df.loc[idx, "vendor"] = "MachineMart"
            df.loc[idx, "category"] = "Equipment"
            df.loc[idx, "amount"] = 18_000.0 + j * 1_000.0
    _mark(df, indexes[: (len(indexes) // 4) * 4], "vendor_burst")


def _inject_category_shift(df: pd.DataFrame, indexes: list[int]) -> None:
    for idx in indexes:
        employee_id = "EMP009"  # HR employee: Equipment is intentionally atypical.
        employee = EMPLOYEES[employee_id]
        df.loc[idx, ["employee_id", "employee_name", "manager_name", "department", "location"]] = [
            employee_id, employee["name"], employee["manager"], employee["department"], employee["location"]
        ]
        df.loc[idx, "date"] = pd.Timestamp("2026-09-15") + pd.Timedelta(days=idx % 5)
        df.loc[idx, "category"] = "Equipment"
        df.loc[idx, "vendor"] = "MachineMart"
        df.loc[idx, "amount"] = 52_000.0
    _mark(df, indexes, "category_shift")


def _inject_location_shift(df: pd.DataFrame, indexes: list[int]) -> None:
    for idx in indexes:
        employee_id = "EMP001"
        employee = EMPLOYEES[employee_id]
        df.loc[idx, ["employee_id", "employee_name", "manager_name", "department"]] = [
            employee_id, employee["name"], employee["manager"], employee["department"]
        ]
        df.loc[idx, "date"] = pd.Timestamp("2026-09-20") + pd.Timedelta(days=idx % 4)
        df.loc[idx, "location"] = "Bengaluru"
        df.loc[idx, "amount"] = round(float(df.loc[idx, "amount"] * 2.3), 2)
    _mark(df, indexes, "location_shift")


def _inject_rounded_repeat(df: pd.DataFrame, indexes: list[int]) -> None:
    for start in range(0, len(indexes), 3):
        group = indexes[start:start + 3]
        if len(group) < 3:
            break
        employee_id = "EMP007"
        employee = EMPLOYEES[employee_id]
        for j, idx in enumerate(group):
            df.loc[idx, ["employee_id", "employee_name", "manager_name", "department", "location"]] = [
                employee_id, employee["name"], employee["manager"], employee["department"], employee["location"]
            ]
            df.loc[idx, "vendor"] = "TravelDesk"
            df.loc[idx, "category"] = "Travel"
            df.loc[idx, "amount"] = 49_999.0
            df.loc[idx, "date"] = pd.Timestamp("2026-06-10") + pd.Timedelta(days=j)
    _mark(df, indexes[: (len(indexes) // 3) * 3], "rounded_repeat")


INJECTORS = {
    "extreme_amount": _inject_extreme_amount,
    "moderate_amount": _inject_moderate_amount,
    "duplicate_payment": _inject_duplicate_payment,
    "split_payment": _inject_split_payment,
    "vendor_burst": _inject_vendor_burst,
    "category_shift": _inject_category_shift,
    "location_shift": _inject_location_shift,
    "rounded_repeat": _inject_rounded_repeat,
}


def generate_transactions(
    rows: int = 1000,
    anomaly_rate: float = 0.02,
    seed: int = 42,
    pattern_mix: list[str] | None = None,
) -> pd.DataFrame:
    """Create a reproducible ledger with mixed fraud-like benchmark patterns."""
    df, rng = _normal_ledger(rows, seed)
    anomaly_count = int(rows * anomaly_rate)
    if anomaly_count <= 0:
        return df

    patterns = pattern_mix or list(INJECTORS)
    # Reserve indices near the end to reduce accidental overlap with source rows.
    candidate = np.arange(max(1, rows // 4), rows)
    if anomaly_count > len(candidate):
        anomaly_count = len(candidate)
    chosen = list(map(int, rng.choice(candidate, size=anomaly_count, replace=False)))

    # Allocate roughly even chunks while respecting group-size patterns.
    chunks = np.array_split(np.array(chosen, dtype=int), len(patterns))
    for pattern, chunk in zip(patterns, chunks):
        indexes = list(map(int, chunk.tolist()))
        if not indexes:
            continue
        injector = INJECTORS[pattern]
        if pattern in {"extreme_amount", "moderate_amount"}:
            injector(df, rng, indexes)
        else:
            injector(df, indexes)

    return df


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "data" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("transactions_clean_100", 100, 0.0, 42),
        ("transactions_1000_mixed_low", 1000, 0.02, 43),
        ("transactions_5000_mixed_low", 5000, 0.02, 44),
        ("transactions_10000_mixed_low", 10000, 0.02, 45),
        ("transactions_1000_mixed_medium", 1000, 0.05, 46),
        ("transactions_1000_mixed_high", 1000, 0.10, 47),
    ]

    for name, rows, anomaly_rate, seed in scenarios:
        df = generate_transactions(rows=rows, anomaly_rate=anomaly_rate, seed=seed)
        csv_path = output_dir / f"{name}.csv"
        excel_path = output_dir / f"{name}.xlsx"
        df.to_csv(csv_path, index=False)
        df.to_excel(excel_path, index=False)
        print(f"Created: {csv_path}")
        print(f"Created: {excel_path}")

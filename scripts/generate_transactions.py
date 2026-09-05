from pathlib import Path

import numpy as np
import pandas as pd


def generate_transactions(
    rows: int = 1000,
    anomaly_rate: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:

    rng = np.random.default_rng(seed)

    employees = [
        "EMP001",
        "EMP002",
        "EMP003",
        "EMP004",
        "EMP005",
    ]

    employee_names = {
        "EMP001": "Aarav",
        "EMP002": "Meera",
        "EMP003": "Kabir",
        "EMP004": "Ishita",
        "EMP005": "Rohan",
    }

    vendors = [
        "OfficeMart",
        "TechSupply",
        "TravelDesk",
        "CloudWorks",
        "EquipHub",
    ]

    categories = [
        "Office",
        "Software",
        "Travel",
        "Equipment",
    ]

    records = []

    for i in range(rows):

        employee_id = rng.choice(employees)

        amount = max(
            100,
            rng.normal(20000, 6000),
        )

        records.append(
            {
                "transaction_id": f"TX{i + 1:06d}",
                "employee_id": employee_id,
                "employee_name": employee_names[employee_id],
                "date": (
                    pd.Timestamp("2026-01-01")
                    + pd.Timedelta(
                        days=int(rng.integers(0, 240))
                    )
                ),
                "vendor": rng.choice(vendors),
                "category": rng.choice(categories),
                "amount": round(float(amount), 2),
                "manager_name": rng.choice(
                    ["Manager A", "Manager B"]
                ),
                "department": rng.choice(
                    [
                        "Finance",
                        "Engineering",
                        "Operations",
                    ]
                ),
                "payment_method": rng.choice(
                    [
                        "Card",
                        "Bank Transfer",
                        "UPI",
                    ]
                ),
                "location": rng.choice(
                    [
                        "Mumbai",
                        "Delhi",
                        "Bengaluru",
                        "Varanasi",
                    ]
                ),
            }
        )

    df = pd.DataFrame(records)

    anomaly_count = int(
        rows * anomaly_rate
    )

    df["synthetic_anomaly"] = False

    if anomaly_count > 0:

        anomaly_indices = rng.choice(
            df.index,
            size=anomaly_count,
            replace=False,
        )

        df.loc[
            anomaly_indices,
            "amount",
        ] *= rng.uniform(
            8,
            20,
            size=anomaly_count,
        )

        df.loc[
            anomaly_indices,
            "synthetic_anomaly",
        ] = True

    return df


if __name__ == "__main__":

    output_dir = Path("data/generated")

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scenarios = [
        {
            "name": "transactions_clean_100",
            "rows": 100,
            "anomaly_rate": 0.0,
            "seed": 42,
        },
        {
            "name": "transactions_1000_low_anomaly",
            "rows": 1000,
            "anomaly_rate": 0.02,
            "seed": 43,
        },
        {
            "name": "transactions_5000_low_anomaly",
            "rows": 5000,
            "anomaly_rate": 0.02,
            "seed": 44,
        },
        {
            "name": "transactions_10000_low_anomaly",
            "rows": 10000,
            "anomaly_rate": 0.02,
            "seed": 45,
        },
        {
            "name": "transactions_1000_medium_anomaly",
            "rows": 1000,
            "anomaly_rate": 0.05,
            "seed": 46,
        },
        {
            "name": "transactions_1000_high_anomaly",
            "rows": 1000,
            "anomaly_rate": 0.10,
            "seed": 47,
        },
    ]

    for scenario in scenarios:

        df = generate_transactions(
            rows=scenario["rows"],
            anomaly_rate=scenario["anomaly_rate"],
            seed=scenario["seed"],
        )

        csv_path = (
            output_dir
            / f"{scenario['name']}.csv"
        )

        excel_path = (
            output_dir
            / f"{scenario['name']}.xlsx"
        )

        df.to_csv(
            csv_path,
            index=False,
        )

        df.to_excel(
            excel_path,
            index=False,
        )

        print(
            f"Created: {csv_path}"
        )

        print(
            f"Created: {excel_path}"
        )
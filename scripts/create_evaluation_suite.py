"""Create the fixed judge-facing evaluation workbook suite.

These files are committed under data/evaluation so a tester can exercise the
system without running the generator first. Ground-truth columns are present
only in valid benchmark files and are ignored during model inference.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from generate_transactions import generate_transactions


def _save(df: pd.DataFrame, path: Path) -> None:
    df.to_excel(path, index=False)


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output = project_root / "data" / "evaluation"
    output.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("01_clean_small", 120, 0.00, 101, None),
        ("02_extreme_amount", 250, 0.04, 102, ["extreme_amount"]),
        ("03_moderate_amount", 300, 0.04, 103, ["moderate_amount"]),
        ("04_duplicate_payment", 250, 0.04, 104, ["duplicate_payment"]),
        ("05_split_payment", 300, 0.06, 105, ["split_payment"]),
        ("06_vendor_burst", 300, 0.08, 106, ["vendor_burst"]),
        ("07_category_shift", 300, 0.04, 107, ["category_shift"]),
        ("08_location_shift", 300, 0.04, 108, ["location_shift"]),
        ("09_rounded_repeat", 300, 0.06, 109, ["rounded_repeat"]),
        ("10_mixed_subtle", 400, 0.06, 110, ["moderate_amount", "category_shift", "location_shift"]),
        ("11_mixed_operational", 500, 0.08, 111, ["duplicate_payment", "split_payment", "vendor_burst", "rounded_repeat"]),
        ("12_mixed_all_patterns", 800, 0.08, 112, None),
        ("13_clean_medium", 1000, 0.00, 113, None),
        ("14_mixed_medium", 1000, 0.05, 114, None),
        ("15_high_anomaly_batch", 1000, 0.12, 115, None),
        ("16_large_clean", 3000, 0.00, 116, None),
        ("17_large_mixed", 3000, 0.05, 117, None),
        # Worst-case systemic ledger: most rows contain strong review signals.
        # This specifically demonstrates that the audit engine also uses external
        # policy/pattern controls, rather than relying only on relative ML distance.
        ("21_systemic_high_anomaly_60", 1000, 0.60, 121, [
            "extreme_amount", "duplicate_payment", "split_payment", "vendor_burst"
        ]),
    ]

    for name, rows, rate, seed, patterns in scenarios:
        df = generate_transactions(rows, rate, seed, patterns)
        _save(df, output / f"{name}.xlsx")

    # Valid workbook with optional fields omitted.
    optional = generate_transactions(300, 0.04, 118, ["moderate_amount", "duplicate_payment"])
    optional = optional.drop(
        columns=["manager_name", "department", "payment_method", "location"],
        errors="ignore",
    )
    _save(optional, output / "18_missing_optional_fields.xlsx")

    # Deliberately invalid workbook: required columns are missing.
    invalid_columns = generate_transactions(80, 0.0, 119).drop(
        columns=["vendor", "category"], errors="ignore"
    )
    _save(invalid_columns, output / "19_invalid_missing_required.xlsx")

    # Deliberately invalid workbook: one amount cannot be normalized.
    invalid_amount = generate_transactions(80, 0.0, 120)
    invalid_amount.loc[3, "amount"] = "not-a-number"
    _save(invalid_amount, output / "20_invalid_amount.xlsx")

    print(f"Created 21 fixed evaluation workbooks in {output}")


if __name__ == "__main__":
    main()

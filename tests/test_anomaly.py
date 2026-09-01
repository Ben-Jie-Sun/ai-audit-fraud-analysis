from datetime import date

import pandas as pd

from app.audit.anomaly import check_amount_anomaly
from app.models.schemas import ExtractedInvoice, FindingStatus

HISTORICAL = pd.DataFrame(
    [
        {"vendor": "ABC Supplies", "invoice_number": "INV-1001", "date": "2026-02-03", "amount": 18500, "category": "Equipment"},
        {"vendor": "ABC Supplies", "invoice_number": "INV-1005", "date": "2026-02-19", "amount": 21000, "category": "Equipment"},
        {"vendor": "Global Traders", "invoice_number": "INV-2002", "date": "2026-02-08", "amount": 26000, "category": "Equipment"},
    ]
)


def make_invoice(**overrides) -> ExtractedInvoice:
    base = dict(
        source_file="test.json",
        vendor="ABC Supplies",
        invoice_number="INV-9999",
        invoice_date=date(2026, 8, 1),
        amount=20000,
        category="Equipment",
    )
    base.update(overrides)
    return ExtractedInvoice(**base)


def test_normal_amount_passes():
    finding = check_amount_anomaly(make_invoice(amount=20000), HISTORICAL)
    assert finding.status == FindingStatus.PASS


def test_high_amount_flagged_as_warning():
    finding = check_amount_anomaly(make_invoice(amount=125000), HISTORICAL)
    assert finding.status == FindingStatus.WARNING
    assert "median" in finding.detail


def test_unknown_category_passes_with_no_data():
    finding = check_amount_anomaly(make_invoice(category="Marketing", amount=999999), HISTORICAL)
    assert finding.status == FindingStatus.PASS

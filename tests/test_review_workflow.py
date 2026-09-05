from app.api.routes import run_pipeline
from app.audit.review_workflow import (
    build_document_review_workflow,
    classify_review_priority,
    route_review,
)
from app.models.schemas import Evidence, Finding, FindingStatus


def _finding(status: FindingStatus, weight: int, title: str = "Test") -> Finding:
    return Finding(
        id="test",
        title=title,
        status=status,
        detail="test detail",
        evidence=[Evidence(label="source", value="unit test")],
        weight=weight,
    )


def test_shared_review_priority_boundaries():
    assert classify_review_priority(0) == "LOW"
    assert classify_review_priority(24) == "LOW"
    assert classify_review_priority(25) == "MEDIUM"
    assert classify_review_priority(49) == "MEDIUM"
    assert classify_review_priority(50) == "HIGH"
    assert classify_review_priority(74) == "HIGH"
    assert classify_review_priority(75) == "CRITICAL"
    assert classify_review_priority(100) == "CRITICAL"


def test_document_non_pass_is_never_silently_auto_cleared():
    workflow = build_document_review_workflow(
        [_finding(FindingStatus.WARNING, 10, "Integrity warning")],
        10,
    )
    assert workflow["review_priority"] == "MEDIUM"
    assert workflow["review_required"] is True
    assert workflow["decision"] == "MANAGER REVIEW"


def test_clean_document_can_auto_clear():
    workflow = build_document_review_workflow(
        [_finding(FindingStatus.PASS, 0)],
        0,
    )
    assert workflow["review_priority"] == "LOW"
    assert workflow["review_required"] is False
    assert workflow["decision"] == "AUTO-CLEARED"


def test_document_and_transaction_share_high_escalation():
    tx = route_review("HIGH", source_type="transaction", manager_name="Manager A")
    doc = route_review("HIGH", source_type="document")
    assert tx[:3] == doc[:3]
    assert tx[0] == "FINANCE REVIEW"
    assert tx[1] == "Finance Manager / Internal Auditor"
    assert tx[2] is True


def test_document_pipeline_returns_phase6_workflow_fields():
    payload = b'''{
        "vendor": "Example Vendor",
        "invoice_number": "INV-P6-001",
        "date": "2026-09-01",
        "payment_date": "2026-09-02",
        "amount": 1000,
        "category": "Office Supplies"
    }'''
    result = run_pipeline("phase6_test.json", payload)
    assert result.review_priority in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert result.decision
    assert result.assigned_reviewer
    assert isinstance(result.review_required, bool)
    assert result.recommended_action
    assert result.audit_reason

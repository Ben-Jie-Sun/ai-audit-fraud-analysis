from app.ai.audit_chat import answer_audit_question


def _tx_result():
    return {
        "row_count": 3,
        "anomaly_count": 2,
        "anomaly_rate": 2 / 3,
        "batch_judgement": "SYSTEMIC REVIEW REQUIRED",
        "batch_reason": "At least 50% of transactions were flagged.",
        "risk_summary": {"review_required": 2, "low": 1, "medium": 0, "high": 1, "critical": 1},
        "data_coverage": {
            "schema_tier": "MEDIUM CONTEXT",
            "recommended_coverage": 0.5,
            "enabled_signals": ["amount deviation", "vendor burst"],
            "skipped_signals": ["location shift"],
        },
        "review_queue": [
            {"transaction_id": "TX002", "risk_level": "HIGH"},
            {"transaction_id": "TX003", "risk_level": "CRITICAL"},
        ],
        "transactions": [
            {
                "transaction_id": "TX001", "employee_id": "EMP001", "employee_name": "Asha",
                "department": "Finance", "amount": 100, "is_anomaly": False,
                "review_required": False, "risk_level": "LOW", "risk_score": 10,
                "decision": "AUTO-CLEARED", "assigned_reviewer": "Automated screening",
            },
            {
                "transaction_id": "TX002", "employee_id": "EMP004", "employee_name": "Arjun",
                "department": "Sales", "amount": 52000, "vendor": "V1", "category": "Travel",
                "is_anomaly": True, "review_required": True, "risk_level": "HIGH", "risk_score": 78,
                "decision": "FINANCE REVIEW", "assigned_reviewer": "Finance Manager / Internal Audit",
                "recommended_action": "Verify supporting evidence.", "audit_reason": "Unusual amount and vendor burst.",
                "pattern_vendor_burst": True, "pattern_duplicate_payment": False,
                "cluster_id": 1, "cluster_distance": 3.2, "isolation_score": 0.21,
            },
            {
                "transaction_id": "TX003", "employee_id": "EMP004", "employee_name": "Arjun",
                "department": "Sales", "amount": 70000, "is_anomaly": True,
                "review_required": True, "risk_level": "CRITICAL", "risk_score": 96,
                "decision": "CRITICAL ESCALATION", "assigned_reviewer": "Senior Auditor / Fraud Investigation",
            },
        ],
    }


def _doc_result():
    return {
        "source_file": "invoice.json",
        "risk_score": 60,
        "review_priority": "HIGH",
        "decision": "FINANCE REVIEW",
        "assigned_reviewer": "Finance Manager / Internal Auditor",
        "review_required": True,
        "audit_reason": "Approval threshold warning requires review.",
        "findings": [
            {"status": "WARNING", "title": "Approval threshold"},
            {"status": "PASS", "title": "Required fields"},
        ],
    }


def ask(q, tx=True, doc=False):
    return answer_audit_question(
        q,
        _tx_result() if tx else None,
        _doc_result() if doc else None,
        allow_llm_wording=False,
    )


def test_transaction_id_is_grounded():
    out = ask("Why was TX002 flagged?")
    assert out["intent"] == "transaction_explanation"
    assert "78/100" in out["answer"]
    assert "vendor burst" in out["answer"].lower()
    assert "fraud verdict" in out["answer"].lower()


def test_employee_summary():
    out = ask("Show anomalies for EMP004")
    assert out["intent"] == "employee_summary"
    assert "**2** were flagged" in out["answer"]
    assert "TX002" in out["answer"] and "TX003" in out["answer"]


def test_department_rate():
    out = ask("Which department has the highest anomaly rate?")
    assert out["intent"] == "department_anomaly_rate"
    assert "Sales" in out["answer"]
    assert "100.0%" in out["answer"]


def test_systemic_batch_answer_uses_computed_reason():
    out = ask("Why is this systemic review?")
    assert out["intent"] == "batch_judgement"
    assert "SYSTEMIC REVIEW REQUIRED" in out["answer"]
    assert "At least 50%" in out["answer"]


def test_schema_coverage():
    out = ask("What signals were skipped because of schema coverage?")
    assert out["intent"] == "schema_coverage"
    assert "location shift" in out["answer"]
    assert "50%" in out["answer"]


def test_document_answer_is_grounded():
    out = ask("Explain the current document audit", tx=False, doc=True)
    assert out["intent"] == "document_summary"
    assert "invoice.json" in out["answer"]
    assert "Approval threshold" in out["answer"]
    assert "does not establish fraud" in out["answer"]


def test_review_queue_combines_transaction_and_document():
    out = ask("How many pending reviews are there?", tx=True, doc=True)
    assert out["intent"] == "review_queue"
    assert "3 pending" in out["answer"]


def test_unsupported_question_does_not_invent_answer():
    out = ask("What is tomorrow's stock price?")
    assert out["intent"] == "unsupported"
    assert "couldn't map" in out["answer"].lower()

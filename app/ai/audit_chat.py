"""Grounded audit assistant for Phase 7.

The assistant is intentionally *downstream* of the audit engines. It never
runs fraud detection, changes risk scores, or invents verdicts. It can only
answer questions from transaction/document results that were already computed
by the application.

Architecture:

    computed audit result -> retrieve relevant facts -> optional LLM wording
                                                 -> deterministic fallback

When an Anthropic key is absent, the assistant remains fully usable through
its deterministic intent handlers. If an LLM is available, it receives only a
small structured fact packet selected by this module, never the raw uploaded
file or an unrestricted transaction ledger.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any

import pandas as pd

from config import LLM_MAX_TOKENS, LLM_MODEL


def _clean(value: Any, default: str = "n/a") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def _money(value: Any) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return _clean(value)


def _pct(value: Any) -> str:
    try:
        number = float(value)
        if number <= 1:
            number *= 100
        return f"{number:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _active_patterns(row: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    for key, value in row.items():
        if not key.startswith("pattern_") or key == "pattern_count":
            continue
        if bool(value):
            patterns.append(key.removeprefix("pattern_").replace("_", " "))
    return patterns


def _find_transaction(question: str, tx_result: dict | None) -> dict | None:
    if not tx_result:
        return None
    transactions = tx_result.get("transactions", [])
    if not transactions:
        return None

    q_upper = question.upper()
    # Prefer exact IDs found in the current result; this avoids making any
    # assumption about a client's transaction-ID format.
    for row in transactions:
        tx_id = _clean(row.get("transaction_id"), "")
        if tx_id and tx_id.upper() in q_upper:
            return row

    # Common fallback such as "TX00428" / "TXN-00428".
    token = re.search(r"\b(?:TXN?|TRANSACTION)[-_ ]?\d+[A-Z0-9_-]*\b", q_upper)
    if token:
        normalized = re.sub(r"[\s_-]", "", token.group(0))
        for row in transactions:
            candidate = re.sub(r"[\s_-]", "", _clean(row.get("transaction_id"), "").upper())
            if candidate == normalized:
                return row
    return None


def _find_employee(question: str, tx_result: dict | None) -> tuple[str, list[dict]] | None:
    if not tx_result:
        return None
    rows = tx_result.get("transactions", [])
    if not rows:
        return None
    q = question.casefold()

    identifiers: list[tuple[str, str]] = []
    for row in rows:
        for field in ("employee_id", "employee_name"):
            value = _clean(row.get(field), "")
            if value:
                identifiers.append((value, field))

    # Longest values first so "EMP004" wins over a shorter accidental match.
    for value, field in sorted(set(identifiers), key=lambda x: len(x[0]), reverse=True):
        if value.casefold() in q:
            matched = [r for r in rows if _clean(r.get(field), "").casefold() == value.casefold()]
            return value, matched
    return None


def _transaction_fact_packet(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": row.get("transaction_id"),
        "employee": row.get("employee_name") or row.get("employee_id"),
        "date": row.get("date"),
        "amount": row.get("amount"),
        "vendor": row.get("vendor"),
        "category": row.get("category"),
        "department": row.get("department"),
        "location": row.get("location"),
        "is_anomaly": bool(row.get("is_anomaly", False)),
        "risk_score": row.get("risk_score"),
        "risk_level": row.get("risk_level"),
        "decision": row.get("decision"),
        "assigned_reviewer": row.get("assigned_reviewer"),
        "recommended_action": row.get("recommended_action"),
        "audit_reason": row.get("audit_reason") or row.get("anomaly_reason"),
        "cluster_id": row.get("cluster_id"),
        "cluster_distance": row.get("cluster_distance"),
        "isolation_score": row.get("isolation_score"),
        "triggered_patterns": _active_patterns(row),
    }


def _answer_transaction(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tx_id = _clean(row.get("transaction_id"))
    risk = _clean(row.get("risk_level"))
    score = row.get("risk_score", "n/a")
    reason = _clean(row.get("audit_reason") or row.get("anomaly_reason"), "No specific anomaly reason was recorded.")
    patterns = _active_patterns(row)
    pattern_text = ", ".join(patterns) if patterns else "no explicit rule-pattern signal"
    reviewer = _clean(row.get("assigned_reviewer"))
    action = _clean(row.get("recommended_action"), "Follow the configured human-review workflow.")
    anomaly_wording = "was flagged for review" if bool(row.get("is_anomaly")) else "was not flagged by the anomaly engine"

    answer = (
        f"**{tx_id} {anomaly_wording}.** Its review priority is **{risk}** "
        f"with risk score **{score}/100**.\n\n"
        f"**Recorded reason:** {reason}\n\n"
        f"**Triggered pattern signals:** {pattern_text}.\n\n"
        f"**Routing:** {_clean(row.get('decision'))} → **{reviewer}**. "
        f"Recommended action: {action}\n\n"
        "This explains the existing audit result; it is not a fraud verdict."
    )
    return answer, _transaction_fact_packet(row)


def _answer_employee(name: str, rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    total = len(rows)
    flagged = [r for r in rows if bool(r.get("is_anomaly", False))]
    review = [r for r in rows if bool(r.get("review_required", False))]
    high = [r for r in rows if _clean(r.get("risk_level"), "").upper() in {"HIGH", "CRITICAL"}]
    ids = [_clean(r.get("transaction_id")) for r in flagged[:12]]
    answer = (
        f"For **{name}**, the cached ledger contains **{total}** transaction(s). "
        f"**{len(flagged)}** were flagged as anomalous, **{len(review)}** require human review, "
        f"and **{len(high)}** are HIGH/CRITICAL priority."
    )
    if ids:
        answer += "\n\nFlagged transaction IDs: " + ", ".join(ids)
        if len(flagged) > len(ids):
            answer += f" … plus {len(flagged) - len(ids)} more."
    answer += "\n\nThese are screening results, not determinations of fraud."
    facts = {
        "employee": name,
        "transaction_count": total,
        "flagged_count": len(flagged),
        "review_count": len(review),
        "high_critical_count": len(high),
        "flagged_transaction_ids": ids,
    }
    return answer, facts


def _answer_department(tx_result: dict) -> tuple[str, dict[str, Any]]:
    df = pd.DataFrame(tx_result.get("transactions", []))
    if df.empty or "department" not in df.columns or df["department"].dropna().empty:
        return (
            "The current ledger does not provide usable **department** data, so I cannot compute a department anomaly rate.",
            {"department_data_available": False},
        )
    usable = df[df["department"].notna() & (df["department"].astype(str).str.strip() != "")].copy()
    if usable.empty:
        return "The current ledger has no usable department values.", {"department_data_available": False}
    grouped = (
        usable.groupby("department", dropna=True)
        .agg(transactions=("transaction_id", "count"), flagged=("is_anomaly", "sum"))
        .reset_index()
    )
    grouped["anomaly_rate"] = grouped["flagged"] / grouped["transactions"]
    grouped = grouped.sort_values(["anomaly_rate", "flagged", "transactions"], ascending=False)
    top = grouped.iloc[0]
    answer = (
        f"**{top['department']}** has the highest anomaly rate in the current cached ledger: "
        f"**{top['anomaly_rate']:.1%}** ({int(top['flagged'])} flagged out of {int(top['transactions'])} transactions).\n\n"
        "This is a descriptive rate for this uploaded batch; it does not imply that the department is fraudulent."
    )
    facts = {
        "top_department": str(top["department"]),
        "anomaly_rate": float(top["anomaly_rate"]),
        "flagged": int(top["flagged"]),
        "transactions": int(top["transactions"]),
    }
    return answer, facts


def _answer_batch(tx_result: dict) -> tuple[str, dict[str, Any]]:
    judgement = _clean(tx_result.get("batch_judgement"))
    reason = _clean(tx_result.get("batch_reason"))
    total = int(tx_result.get("row_count", 0) or 0)
    flagged = int(tx_result.get("anomaly_count", 0) or 0)
    review = int((tx_result.get("risk_summary") or {}).get("review_required", 0) or 0)
    rate = tx_result.get("anomaly_rate", 0)
    answer = (
        f"The current transaction batch is **{judgement}**. "
        f"It contains **{total}** transactions, **{flagged}** flagged anomalies ({_pct(rate)}), "
        f"and **{review}** item(s) routed for human review.\n\n"
        f"**Why:** {reason}"
    )
    facts = {
        "batch_judgement": judgement,
        "batch_reason": reason,
        "transactions": total,
        "flagged": flagged,
        "anomaly_rate": rate,
        "review_required": review,
    }
    return answer, facts


def _answer_risk_policy() -> tuple[str, dict[str, Any]]:
    answer = (
        "The system uses four **review-priority** levels, not fraud probabilities:\n\n"
        "- **LOW** → automated screening can clear the row when no material review signal is present.\n"
        "- **MEDIUM** → manager review.\n"
        "- **HIGH** → Finance Manager / Internal Audit review.\n"
        "- **CRITICAL** → Senior Auditor / Fraud Investigation escalation.\n\n"
        "A higher level comes from the combined evidence already calculated by the anomaly engine, explicit audit-pattern checks and policy controls. "
        "The score prioritizes review; it does not prove fraud."
    )
    return answer, {"risk_levels": ["LOW", "MEDIUM", "HIGH", "CRITICAL"], "meaning": "review priority"}


def _answer_schema(tx_result: dict) -> tuple[str, dict[str, Any]]:
    coverage = tx_result.get("data_coverage", {}) or {}
    tier = _clean(coverage.get("schema_tier"))
    context = coverage.get("recommended_coverage")
    enabled = coverage.get("enabled_signals", []) or []
    skipped = coverage.get("skipped_signals", []) or []
    answer = f"The current ledger is classified as **{tier}** schema context"
    if context is not None:
        answer += f" with **{float(context):.0%} recommended-context coverage**"
    answer += "."
    if enabled:
        answer += "\n\n**Enabled signals:** " + ", ".join(map(str, enabled)) + "."
    if skipped:
        answer += "\n\n**Skipped signals:** " + ", ".join(map(str, skipped)) + "."
    else:
        answer += "\n\nNo context-specific signal is recorded as skipped."
    answer += "\n\nCoverage measures supplied data context, not model confidence."
    facts = {
        "schema_tier": tier,
        "recommended_coverage": context,
        "enabled_signals": enabled,
        "skipped_signals": skipped,
    }
    return answer, facts


def _answer_document(doc_result: dict) -> tuple[str, dict[str, Any]]:
    source = _clean(doc_result.get("source_file"), "current document")
    priority = _clean(doc_result.get("review_priority"))
    score = doc_result.get("risk_score", "n/a")
    reason = _clean(doc_result.get("audit_reason"), "No audit reason was recorded.")
    findings = [
        f for f in doc_result.get("findings", [])
        if _clean(f.get("status"), "PASS").upper() != "PASS"
    ]
    labels = [f"{_clean(f.get('status'))}: {_clean(f.get('title'))}" for f in findings[:8]]
    answer = (
        f"The cached document **{source}** has review priority **{priority}** with risk score **{score}/100**.\n\n"
        f"**Audit reason:** {reason}\n\n"
        f"**Routing:** {_clean(doc_result.get('decision'))} → **{_clean(doc_result.get('assigned_reviewer'))}**."
    )
    if labels:
        answer += "\n\nNon-pass findings: " + "; ".join(labels) + "."
    answer += "\n\nThis summarizes the computed controls; it does not establish fraud."
    facts = {
        "source_file": source,
        "risk_score": score,
        "review_priority": priority,
        "audit_reason": reason,
        "decision": doc_result.get("decision"),
        "assigned_reviewer": doc_result.get("assigned_reviewer"),
        "findings": labels,
    }
    return answer, facts


def _answer_review_queue(tx_result: dict | None, doc_result: dict | None) -> tuple[str, dict[str, Any]]:
    tx_queue = (tx_result or {}).get("review_queue", []) or []
    doc_required = bool((doc_result or {}).get("review_required", False))
    priorities = Counter(_clean(r.get("risk_level"), "UNKNOWN") for r in tx_queue)
    if doc_required:
        priorities[_clean((doc_result or {}).get("review_priority"), "UNKNOWN")] += 1
    total = len(tx_queue) + int(doc_required)
    answer = f"The cached analyses currently contain **{total} pending human-review item(s)**."
    if total:
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        pieces = [f"{level}: {priorities[level]}" for level in order if priorities[level]]
        if pieces:
            answer += "\n\nPriority breakdown — " + ", ".join(pieces) + "."
    answer += "\n\nThe queue is a routing aid; reviewers still validate evidence and make the final decision."
    return answer, {"pending_items": total, "priority_breakdown": dict(priorities)}


def _try_llm_wording(question: str, facts: dict[str, Any], deterministic_answer: str) -> str | None:
    """Optionally improve wording without expanding the factual scope.

    The deterministic answer is itself included as an allowed fact. If the
    external model is unavailable, the caller simply uses it directly.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    packet = {
        "question": question,
        "retrieved_facts": facts,
        "deterministic_answer": deterministic_answer,
    }
    system = (
        "You are a grounded audit-results assistant. Answer ONLY from the JSON facts supplied. "
        "Never infer that a person, transaction, document, merchant, department or company committed fraud. "
        "An anomaly is not fraud and a risk score is not a fraud probability. "
        "Do not add facts, causes, external knowledge or recommendations that are absent from the packet. "
        "If the packet is insufficient, say so. Keep the answer concise and preserve numerical values exactly."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=min(LLM_MAX_TOKENS, 500),
            system=system,
            messages=[{"role": "user", "content": "AUDIT_FACTS_JSON:\n" + json.dumps(packet, default=str)}],
        )
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        text = "\n".join(parts).strip()
        return text or None
    except Exception:
        return None


def answer_audit_question(
    question: str,
    transaction_result: dict | None = None,
    document_result: dict | None = None,
    *,
    allow_llm_wording: bool = True,
) -> dict[str, Any]:
    """Answer one question from already-computed audit results.

    Returns a small envelope used by the UI and tests:
      answer: markdown text
      intent: selected deterministic retrieval intent
      source: deterministic_grounded or llm_grounded
      facts: the bounded fact packet that supported the answer
    """
    question = (question or "").strip()
    if not question:
        return {
            "answer": "Ask a question about the currently analysed transactions or document audit.",
            "intent": "empty",
            "source": "deterministic_grounded",
            "facts": {},
        }

    q = question.casefold()
    tx_row = _find_transaction(question, transaction_result)
    employee_match = _find_employee(question, transaction_result)

    if tx_row is not None:
        answer, facts = _answer_transaction(tx_row)
        intent = "transaction_explanation"
    elif employee_match is not None and any(term in q for term in ["anomal", "flag", "review", "transaction", "risk"]):
        answer, facts = _answer_employee(*employee_match)
        intent = "employee_summary"
    elif transaction_result and "department" in q and any(term in q for term in ["highest", "most", "rate", "anomal", "flag"]):
        answer, facts = _answer_department(transaction_result)
        intent = "department_anomaly_rate"
    elif transaction_result and any(term in q for term in ["systemic", "batch", "conditional pass", "batch judgement", "batch judgment"]):
        answer, facts = _answer_batch(transaction_result)
        intent = "batch_judgement"
    elif any(phrase in q for phrase in ["what triggers high", "why high", "risk level", "risk levels", "critical", "review priority"]):
        answer, facts = _answer_risk_policy()
        intent = "risk_policy"
    elif transaction_result and any(term in q for term in ["schema", "coverage", "column", "skipped signal", "enabled signal"]):
        answer, facts = _answer_schema(transaction_result)
        intent = "schema_coverage"
    elif document_result and any(term in q for term in ["document", "invoice", "finding", "audit result", "why flagged"]):
        answer, facts = _answer_document(document_result)
        intent = "document_summary"
    elif any(phrase in q for phrase in ["review queue", "pending review", "pending human", "how many reviews"]):
        answer, facts = _answer_review_queue(transaction_result, document_result)
        intent = "review_queue"
    elif transaction_result and any(term in q for term in ["summary", "overview", "how many", "flagged", "anomalies", "anomaly rate"]):
        answer, facts = _answer_batch(transaction_result)
        intent = "transaction_summary"
    elif document_result and not transaction_result:
        answer, facts = _answer_document(document_result)
        intent = "document_summary"
    else:
        scopes = []
        if transaction_result:
            scopes.append("transaction analysis")
        if document_result:
            scopes.append("document audit")
        if not scopes:
            answer = (
                "There is no cached audit result to query yet. Run **Transaction Analysis** or **Document Audit** first."
            )
        else:
            answer = (
                "I couldn't map that question to evidence in the cached " + " and ".join(scopes) + ". "
                "Try asking about a transaction ID, an employee, the batch judgement, department anomaly rate, "
                "schema coverage, risk levels, pending reviews, or the current document audit."
            )
        facts = {"available_scopes": scopes}
        intent = "unsupported"

    source = "deterministic_grounded"
    if allow_llm_wording and intent not in {"unsupported", "empty"}:
        llm_answer = _try_llm_wording(question, facts, answer)
        if llm_answer:
            answer = llm_answer
            source = "llm_grounded"

    return {"answer": answer, "intent": intent, "source": source, "facts": facts}

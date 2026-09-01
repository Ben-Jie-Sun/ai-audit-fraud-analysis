from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.ai.explainer import generate_summary
from app.audit.anomaly import check_amount_anomaly, load_historical
from app.audit.rules import run_all_rules
from app.audit.scoring import classify_risk, compute_risk_score
from app.extraction.document_parser import parse_document
from app.models.schemas import AuditResult
from config import HISTORICAL_TRANSACTIONS_PATH, SAMPLE_DIR

router = APIRouter()


def run_pipeline(filename: str, content: bytes) -> AuditResult:
    invoice = parse_document(filename, content)
    historical = load_historical(HISTORICAL_TRANSACTIONS_PATH)

    findings = run_all_rules(invoice, historical)
    findings.append(check_amount_anomaly(invoice, historical))

    risk_score = compute_risk_score(findings)
    risk_level = classify_risk(risk_score)
    summary, source = generate_summary(invoice, findings, risk_score)

    return AuditResult(
        source_file=filename,
        extracted=invoice,
        findings=findings,
        risk_score=risk_score,
        risk_level=risk_level,
        ai_summary=summary,
        ai_summary_source=source,
    )


@router.post("/audit/upload", response_model=AuditResult)
async def audit_upload(file: UploadFile = File(...)) -> AuditResult:
    content = await file.read()
    try:
        return run_pipeline(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/audit/sample/{sample_name}", response_model=AuditResult)
async def audit_sample(sample_name: str) -> AuditResult:
    """Run the pipeline on a bundled sample document, for demos."""
    path = os.path.join(SAMPLE_DIR, sample_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"No sample named '{sample_name}'")
    with open(path, "rb") as fh:
        content = fh.read()
    try:
        return run_pipeline(sample_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit/samples")
async def list_samples() -> list[str]:
    """List bundled sample documents that /audit/sample/{name} can run."""
    return sorted(
        f for f in os.listdir(SAMPLE_DIR) if f.endswith((".json", ".csv"))
        and f != "historical_transactions.csv"
    )

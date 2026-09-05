from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.ai.explainer import generate_summary
from app.audit.anomaly import (
    check_amount_anomaly,
    detect_transaction_anomalies,
    load_historical,
)
from app.audit.rules import run_all_rules
from app.audit.scoring import classify_risk, compute_risk_score
from app.extraction.document_parser import parse_document
from app.extraction.transaction_parser import load_transaction_file
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
        f
        for f in os.listdir(SAMPLE_DIR)
        if f.endswith((".json", ".csv"))
        and f != "historical_transactions.csv"
    )


@router.post("/transactions/analyze")
async def analyze_transactions(
    file: UploadFile = File(...)
):
    filename = file.filename or ""

    extension = os.path.splitext(filename)[1].lower()

    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(
            status_code=400,
            detail="Transaction ledger must be CSV or XLSX.",
        )

    content = await file.read()

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension,
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        df = load_transaction_file(temp_path)

        df = detect_transaction_anomalies(df)

        df["decision"] = "AUTO-CLEARED"
        df["review_required"] = False

        df.loc[
            df["is_anomaly"],
            "decision",
        ] = "RECHECK"

        df.loc[
            df["is_anomaly"],
            "review_required",
        ] = True

        df["audit_reason"] = (
            "Transaction passed automated anomaly screening."
        )

        df.loc[
            df["is_anomaly"],
            "audit_reason",
        ] = (
            "Transaction was identified as statistically unusual "
            "and requires human review."
        )

        anomaly_df = df[
            df["is_anomaly"]
        ].copy()

        preview_df = df.head(20).copy()

        preview_df["date"] = (
            preview_df["date"]
            .dt.strftime("%Y-%m-%d")
        )

        anomaly_df["date"] = (
            anomaly_df["date"]
            .dt.strftime("%Y-%m-%d")
        )

        anomaly_count = int(
            df["is_anomaly"].sum()
        )

        total_count = len(df)

        anomaly_rate = (
            anomaly_count / total_count
            if total_count > 0
            else 0
        )

        if anomaly_rate < 0.05:
            batch_judgement = "CONDITIONAL PASS"

            batch_reason = (
                "Less than 5% of transactions were flagged. "
                "Non-flagged transactions passed automated screening, "
                "while flagged transactions require human review."
            )

        else:
            batch_judgement = "REVIEW REQUIRED"

            batch_reason = (
                "5% or more of transactions were flagged. "
                "The transaction batch requires additional review."
            )

        all_transactions_df = df.copy()

        all_transactions_df["date"] = (
            all_transactions_df["date"]
            .dt.strftime("%Y-%m-%d")
        )

        return {
            "source_file": filename,

            "row_count": total_count,

            "columns": list(df.columns),

            "anomaly_count": anomaly_count,

            "normal_count": (
                total_count - anomaly_count
            ),

            "anomaly_rate": anomaly_rate,

            "batch_judgement": batch_judgement,

            "batch_reason": batch_reason,

            "preview": preview_df.to_dict(
                orient="records"
            ),

            "anomalies": anomaly_df.to_dict(
                orient="records"
            ),

            "transactions": (
                all_transactions_df.to_dict(
                    orient="records"
                )
            ),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to process transaction ledger: "
                f"{exc}"
            ),
        ) from exc

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
from app.audit.scoring import classify_risk, compute_risk_score
from app.models.schemas import Finding, FindingStatus, RiskLevel


def make_finding(status: FindingStatus, weight: int) -> Finding:
    return Finding(
        id="x", title="x", status=status, detail="x", evidence=[], weight=weight
    )


def test_score_sums_only_non_pass_findings():
    findings = [
        make_finding(FindingStatus.PASS, 20),
        make_finding(FindingStatus.WARNING, 15),
        make_finding(FindingStatus.FAIL, 25),
    ]
    assert compute_risk_score(findings) == 40


def test_score_caps_at_100():
    findings = [make_finding(FindingStatus.FAIL, 60) for _ in range(5)]
    assert compute_risk_score(findings) == 100


def test_classify_low():
    assert classify_risk(10) == RiskLevel.LOW


def test_classify_medium():
    assert classify_risk(50) == RiskLevel.MEDIUM


def test_classify_high():
    assert classify_risk(90) == RiskLevel.HIGH

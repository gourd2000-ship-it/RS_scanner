from dataclasses import dataclass, field


@dataclass(slots=True)
class QualityFinding:
    rule_id: str
    severity: str
    path: str
    line: int | None
    message: str
    suggestion: str | None = None


@dataclass(slots=True)
class QualityCheckResult:
    name: str
    passed: bool
    findings: list[QualityFinding] = field(default_factory=list)
    details: str | None = None


@dataclass(slots=True)
class AutoCorrectionReport:
    success: bool
    attempts: int
    summary: str
    failing_checks: list[QualityCheckResult] = field(default_factory=list)

from pathlib import Path

from app.ops.quality.models import QualityCheckResult, QualityFinding
from app.ops.quality.policy import DEFAULT_GARBAGE_RULES, GarbageRule, iter_candidate_files
from app.ops.quality.reporting import write_check_report


class GarbageCollectorAgent:
    def __init__(self, project_root: str | Path, rules: tuple[GarbageRule, ...] = DEFAULT_GARBAGE_RULES) -> None:
        self.project_root = Path(project_root)
        self.rules = rules

    def scan(self) -> QualityCheckResult:
        findings: list[QualityFinding] = []
        for rule in self.rules:
            for file_path in iter_candidate_files(self.project_root, rule.include_globs):
                findings.extend(self._scan_file(file_path, rule))

        result = QualityCheckResult(
            name="garbage-collector",
            passed=not any(f.severity == "error" for f in findings),
            findings=findings,
            details=f"found {len(findings)} cleanup candidate(s)",
        )
        output_dir = self.project_root / ".codex" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        write_check_report([result], output_dir / "garbage-collector.json")
        return result

    def _scan_file(self, file_path: Path, rule: GarbageRule) -> list[QualityFinding]:
        findings: list[QualityFinding] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return findings

        for line_no, line in enumerate(lines, start=1):
            if rule.pattern not in line:
                continue
            if _is_rule_metadata_line(line, rule.pattern):
                continue
            if _is_quoted_pattern_occurrence(line, rule.pattern):
                continue
            if rule.rule_id == "commented-code" and not _looks_like_commented_code(line):
                continue
            findings.append(
                QualityFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    path=str(file_path.relative_to(self.project_root)),
                    line=line_no,
                    message=rule.message,
                    suggestion=rule.suggestion,
                )
            )
        return findings


def _looks_like_commented_code(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("# ") and any(token in stripped for token in ("=", "return", "if ", "for ", "while "))


def _is_rule_metadata_line(line: str, pattern: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("pattern=") or stripped.startswith("rule_id=") or stripped.startswith("message=")


def _is_quoted_pattern_occurrence(line: str, pattern: str) -> bool:
    return f'"{pattern}"' in line or f"'{pattern}'" in line

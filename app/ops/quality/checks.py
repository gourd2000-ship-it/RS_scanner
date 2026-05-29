import shutil
import subprocess
import sys
from pathlib import Path

from app.ops.quality.models import QualityCheckResult, QualityFinding


def run_compile_check(project_root: Path) -> QualityCheckResult:
    cmd = [sys.executable, "-m", "compileall", "app", "tests"]
    completed = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, check=False)
    passed = completed.returncode == 0
    return QualityCheckResult(
        name="compileall",
        passed=passed,
        details=(completed.stdout + completed.stderr).strip() or None,
        findings=[] if passed else [
            QualityFinding(
                rule_id="compileall",
                severity="error",
                path="app/",
                line=None,
                message="python compileall failed",
                suggestion="fix syntax or import errors before saving",
            )
        ],
    )


def run_pytest_check(project_root: Path) -> QualityCheckResult:
    if shutil.which("pytest") is None:
        return QualityCheckResult(
            name="pytest",
            passed=True,
            details="pytest not installed; skipping",
        )

    completed = subprocess.run(["pytest"], cwd=project_root, capture_output=True, text=True, check=False)
    passed = completed.returncode == 0
    return QualityCheckResult(
        name="pytest",
        passed=passed,
        details=(completed.stdout + completed.stderr).strip() or None,
        findings=[] if passed else [
            QualityFinding(
                rule_id="pytest",
                severity="error",
                path="tests/",
                line=None,
                message="pytest suite failed",
                suggestion="fix failing tests or update stale expectations",
            )
        ],
    )

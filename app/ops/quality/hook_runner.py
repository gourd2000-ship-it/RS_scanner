from pathlib import Path

from app.ops.quality.checks import run_compile_check, run_pytest_check
from app.ops.quality.models import QualityCheckResult
from app.ops.quality.reporting import write_check_report


class HookRunner:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)

    def run(self) -> list[QualityCheckResult]:
        results = [
            run_compile_check(self.project_root),
            run_pytest_check(self.project_root),
        ]
        output_dir = self.project_root / ".codex" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        write_check_report(results, output_dir / "quality-gate.json")
        return results

    def exit_code(self) -> int:
        return 0 if all(result.passed for result in self.run()) else 1

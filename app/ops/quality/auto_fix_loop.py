import os
import subprocess
from pathlib import Path

from app.ops.quality.auto_fix_templates import write_prompt_template
from app.ops.quality.hook_runner import HookRunner
from app.ops.quality.models import AutoCorrectionReport
from app.ops.quality.reporting import write_auto_correction_report


class AutoCorrectionLoop:
    """Quality gate + optional AI/self-fix loop.

    If `CODEX_AUTO_FIX_COMMAND` is configured, failed checks trigger that command.
    The command receives a report path via `CODEX_QUALITY_REPORT`.
    """

    def __init__(self, project_root: str | Path, max_attempts: int = 2) -> None:
        self.project_root = Path(project_root)
        self.max_attempts = max_attempts
        self.hook_runner = HookRunner(self.project_root)

    def run(self) -> AutoCorrectionReport:
        report_dir = self.project_root / ".codex" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, self.max_attempts + 1):
            results = self.hook_runner.run()
            failing = [result for result in results if not result.passed]
            if not failing:
                report = AutoCorrectionReport(
                    success=True,
                    attempts=attempt,
                    summary="quality gate passed",
                    failing_checks=[],
                )
                write_auto_correction_report(report, report_dir / "auto-correction.json")
                return report

            if not self._invoke_auto_fix():
                report = AutoCorrectionReport(
                    success=False,
                    attempts=attempt,
                    summary="quality gate failed and no auto-fix command was configured",
                    failing_checks=failing,
                )
                write_auto_correction_report(report, report_dir / "auto-correction.json")
                return report

        final_results = self.hook_runner.run()
        failing = [result for result in final_results if not result.passed]
        report = AutoCorrectionReport(
            success=False,
            attempts=self.max_attempts,
            summary="quality gate still failing after auto-correction attempts",
            failing_checks=failing,
        )
        write_auto_correction_report(report, report_dir / "auto-correction.json")
        return report

    def _invoke_auto_fix(self) -> bool:
        command = os.getenv("CODEX_AUTO_FIX_COMMAND")
        if not command:
            return False

        report_path = self.project_root / ".codex" / "reports" / "quality-gate.json"
        prompt_path = self.project_root / ".codex" / "reports" / "auto-fix-prompt.txt"
        write_prompt_template(self.project_root, report_path, prompt_path)
        env = os.environ.copy()
        env["CODEX_QUALITY_REPORT"] = str(report_path)
        env["CODEX_AUTO_FIX_PROMPT"] = str(prompt_path)
        # The configured command is often a module shipped by this project.  A
        # quality run may target a temporary checkout (as the unit tests do),
        # so the subprocess must still be able to import the command module
        # from the repository that owns this loop.
        package_root = str(Path(__file__).resolve().parents[3])
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            package_root
            if not existing_pythonpath
            else os.pathsep.join((package_root, existing_pythonpath))
        )
        command_cwd = self.project_root
        # A temporary/minimal target may not contain the bundled command
        # module.  In that case run the module from its owning checkout while
        # keeping the quality report paths absolute.
        bundled_command = self.project_root / "app" / "ops" / "quality" / "auto_fix_command.py"
        if not bundled_command.exists():
            command_cwd = Path(__file__).resolve().parents[3]
        completed = subprocess.run(command, cwd=command_cwd, shell=True, env=env, check=False)
        return completed.returncode == 0

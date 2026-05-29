import json
import os
from pathlib import Path

from app.ops.quality.auto_fix_loop import AutoCorrectionLoop


def test_auto_fix_loop_writes_prompt_when_command_is_configured(tmp_path: Path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")

    command = f"{os.sys.executable} -m app.ops.quality.auto_fix_command"
    monkeypatch.setenv("CODEX_AUTO_FIX_COMMAND", command)

    report = AutoCorrectionLoop(tmp_path, max_attempts=1).run()

    assert report.success is False
    assert (tmp_path / ".codex" / "reports" / "auto-fix-prompt.txt").exists()
    assert (tmp_path / ".codex" / "reports" / "auto-fix-command-summary.json").exists()

    summary = json.loads((tmp_path / ".codex" / "reports" / "auto-fix-command-summary.json").read_text(encoding="utf-8"))
    assert "compileall" in summary["failing_checks"]

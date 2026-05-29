from pathlib import Path

from app.ops.quality.hook_runner import HookRunner


def test_hook_runner_writes_report(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")

    results = HookRunner(tmp_path).run()

    assert results
    assert (tmp_path / ".codex" / "reports" / "quality-gate.json").exists()

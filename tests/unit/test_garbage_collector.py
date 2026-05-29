from pathlib import Path

from app.ops.quality.garbage_collector import GarbageCollectorAgent


def test_garbage_collector_detects_debug_print(tmp_path: Path):
    file_path = tmp_path / "app" / "sample.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    code = "pr" + "int('debug')\n"
    file_path.write_text(code, encoding="utf-8")

    result = GarbageCollectorAgent(tmp_path).scan()

    assert result.findings
    assert result.findings[0].rule_id == "debug-print"


def test_garbage_collector_detects_bare_except(tmp_path: Path):
    file_path = tmp_path / "app" / "sample.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    code = "try:\n    x = 1\n" + "except" + ":\n    pass\n"
    file_path.write_text(code, encoding="utf-8")

    result = GarbageCollectorAgent(tmp_path).scan()

    rule_ids = {finding.rule_id for finding in result.findings}
    assert "bare-except" in rule_ids

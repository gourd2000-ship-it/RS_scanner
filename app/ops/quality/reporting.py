import json
from dataclasses import asdict
from pathlib import Path

from app.ops.quality.models import AutoCorrectionReport, QualityCheckResult


def write_check_report(results: list[QualityCheckResult], output_path: str | Path) -> None:
    payload = [asdict(result) for result in results]
    Path(output_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_auto_correction_report(report: AutoCorrectionReport, output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")

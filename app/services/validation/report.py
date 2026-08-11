"""Persist deterministic validation results as operator-readable JSON."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.services.validation.data_quality import ValidationResult


def write_validation_report(
    result: ValidationResult,
    *,
    output: str | Path | None = None,
) -> Path:
    """Write one validation result atomically and return its path.

    Report generation is deliberately separate from validation itself so a
    filesystem problem cannot alter the validation decision or the source
    price data.  Callers may decide whether a write failure should be fatal.
    """

    if output is None:
        job_id = result.run.crawl_job_id
        filename = f"job_{job_id}.json" if job_id is not None else f"validation_{result.run.id}.json"
        output_path = Path(get_settings().validation_report_dir) / filename
    else:
        output_path = Path(output)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return output_path

"""Read-only JSON persistence for KRX/Naver reconciliation evidence."""

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

from app.services.monitoring.universe_reconciliation import UniverseReconciliationReport


def write_reconciliation_report(
    report: UniverseReconciliationReport,
    *,
    output_dir: Path,
    report_stem: str,
    generated_at: datetime | None = None,
) -> Path:
    """Persist a JSON report only; it never changes universe or target data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    output = output_dir / f"{report_stem}.json"
    payload = {
        **asdict(report),
        "generated_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output

"""종목 universe legacy/stale 후보를 읽기 전용으로 감사한다.

예시:
    .venv/bin/python scripts/audit_universe.py --output-dir reports/universe_audit
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.universe_audit_repository import UniverseAuditRepository
from app.services.universe_audit import (
    AuditSymbol,
    UniverseAuditReport,
    build_universe_audit_report,
)


_CSV_FIELDS = (
    "code",
    "name",
    "market",
    "symbol_type",
    "last_snapshot_id",
    "reason_codes",
    "replacement_code",
    "prefix_matches",
)


def write_audit_reports(
    report: UniverseAuditReport,
    *,
    output_dir: Path,
    report_stem: str,
    generated_at: datetime | None = None,
) -> tuple[Path, Path]:
    """감사 결과를 JSON 요약과 CSV 후보 목록으로 저장한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report_stem}.json"
    csv_path = output_dir / f"{report_stem}.csv"

    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    report_payload = {
        **report.to_dict(),
        "generated_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    json_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for candidate in report.candidates:
            writer.writerow(
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "market": candidate.market,
                    "symbol_type": candidate.symbol_type,
                    "last_snapshot_id": candidate.last_snapshot_id,
                    "reason_codes": ",".join(candidate.reason_codes),
                    "replacement_code": candidate.replacement_code or "",
                    "prefix_matches": ",".join(candidate.prefix_matches),
                }
            )
    return json_path, csv_path


def _latest_completed_snapshot(session, snapshot_id: int | None):
    if snapshot_id is not None:
        snapshot = session.get(SymbolUniverseSnapshot, snapshot_id)
        if snapshot is None or snapshot.status != "completed":
            raise ValueError(f"completed universe snapshot을 찾을 수 없습니다: {snapshot_id}")
        return snapshot

    return session.scalar(
        select(SymbolUniverseSnapshot)
        .where(SymbolUniverseSnapshot.status == "completed")
        .order_by(
            SymbolUniverseSnapshot.finished_at.desc(),
            SymbolUniverseSnapshot.id.desc(),
        )
        .limit(1)
    )


def build_report_from_database(*, snapshot_id: int | None) -> UniverseAuditReport:
    """DB를 변경하지 않고 active symbol과 기준 snapshot을 읽어 report를 만든다."""
    with SessionLocal() as session:
        snapshot = _latest_completed_snapshot(session, snapshot_id)
        symbol_rows = session.execute(
            select(
                Symbol.code,
                Symbol.name,
                Symbol.market,
                Symbol.symbol_type,
                Symbol.is_active,
                Symbol.last_snapshot_id,
            )
            .where(Symbol.is_active.is_(True))
            .order_by(Symbol.code)
        )
        symbols = [
            AuditSymbol(
                code=row.code,
                name=row.name,
                market=row.market,
                symbol_type=row.symbol_type,
                is_active=row.is_active,
                last_snapshot_id=row.last_snapshot_id,
            )
            for row in symbol_rows
        ]
        return build_universe_audit_report(
            symbols=symbols,
            latest_completed_snapshot_id=snapshot.id if snapshot is not None else None,
        )


def persist_audit_run(
    session,
    *,
    snapshot_id: int | None,
    report: UniverseAuditReport,
    requested_by: str,
):
    """명시적으로 승인 workflow를 시작할 때만 audit run을 생성한다."""
    return UniverseAuditRepository(session).create_run(
        snapshot_id=snapshot_id,
        report=report,
        requested_by=requested_by,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="종목 universe dry-run 감사")
    parser.add_argument(
        "--snapshot-id",
        type=int,
        default=None,
        help="기준으로 사용할 completed snapshot ID",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/universe_audit"),
        help="JSON/CSV report 저장 경로",
    )
    parser.add_argument(
        "--create-run",
        action="store_true",
        help="승인 workflow용 pending audit run도 함께 생성",
    )
    parser.add_argument(
        "--requested-by",
        help="--create-run 사용 시 audit 요청자",
    )
    args = parser.parse_args()

    if args.create_run and not args.requested_by:
        parser.error("--create-run 사용 시 --requested-by가 필요합니다")

    try:
        report = build_report_from_database(snapshot_id=args.snapshot_id)
    except ValueError as exc:
        parser.error(str(exc))

    generated_at = datetime.now(UTC)
    json_path, csv_path = write_audit_reports(
        report,
        output_dir=args.output_dir,
        report_stem=f"universe_audit_{generated_at.strftime('%Y%m%d_%H%M%S')}",
        generated_at=generated_at,
    )
    run_id: int | None = None
    if args.create_run:
        with SessionLocal() as session:
            run = persist_audit_run(
                session,
                snapshot_id=report.latest_completed_snapshot_id,
                report=report,
                requested_by=args.requested_by,
            )
            session.commit()
            run_id = run.id
    print(
        "universe audit completed: "
        f"candidates={len(report.candidates)} json={json_path} csv={csv_path}"
        + (f" run_id={run_id}" if run_id is not None else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

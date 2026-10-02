#!/usr/bin/env python3
"""KRX listing/delisting CSV에서 재사용 코드에 안전한 canonical identity를 만든다."""

import argparse
import json
from pathlib import Path

from sqlalchemy import inspect, select

from app.core.database import SessionLocal, session_scope
from app.models.instrument import Instrument
from app.services.krx_listing_csv import (
    ExistingInstrument,
    build_krx_lifecycles,
    plan_identity_reconciliation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path, help="KRX CSV 파일; 반복 가능")
    parser.add_argument("--report", required=True, type=Path, help="reconciliation 검토 JSON")
    parser.add_argument("--apply", action="store_true", help="identity 변경을 commit한다 (기본은 dry-run)")
    args = parser.parse_args()

    files = [(str(path), path.read_bytes()) for path in sorted(args.input)]
    lifecycles = build_krx_lifecycles(files)
    with SessionLocal() as session:
        existing = [
            ExistingInstrument(
                row.id, row.krx_short_code, row.market, row.listed_at, row.delisted_at, row.listing_status,
            )
            for row in session.scalars(select(Instrument).order_by(Instrument.id))
        ]
    plan = plan_identity_reconciliation(lifecycles, existing)
    report = {
        "input_file_count": len(files),
        "lifecycle_count": len(lifecycles),
        "existing_instrument_count": len(existing),
        "update_count": len(plan.updates),
        "create_count": len(plan.creates),
        "unresolved_count": len(plan.unresolved),
        "updates": [
            {"instrument_id": row.instrument_id, "listed_at": row.listed_at.isoformat()}
            for row in plan.updates
        ],
        "creates": [
            {
                "code": row.krx_short_code,
                "name": row.name,
                "market": row.market,
                "listed_at": row.listed_at.isoformat(),
                "delisted_at": row.delisted_at.isoformat(),
                "listing_status": row.listing_status,
            }
            for row in plan.creates
        ],
        "unresolved": plan.unresolved,
        "applied": args.apply,
    }
    if args.apply:
        _require_reused_code_schema()
        with session_scope() as session:
            for row in plan.updates:
                instrument = session.get(Instrument, row.instrument_id)
                if instrument is None:
                    raise ValueError(f"instrument를 찾을 수 없습니다: {row.instrument_id}")
                if instrument.listed_at is not None or instrument.delisted_at is not None:
                    raise ValueError(f"instrument {row.instrument_id}의 날짜가 dry-run 이후 변경됐습니다")
                instrument.listed_at = row.listed_at
            for row in plan.creates:
                session.add(Instrument(
                    krx_short_code=row.krx_short_code,
                    isin=None,
                    name=row.name,
                    market=row.market,
                    security_type="stock",
                    listed_at=row.listed_at,
                    delisted_at=row.delisted_at,
                    listing_status=row.listing_status,
                ))
    _write_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"updates", "creates", "unresolved"}}, ensure_ascii=False, sort_keys=True))
    return 0


def _require_reused_code_schema() -> None:
    """기존 단일-code unique 제약에서 역사 identity를 절대 부분 적용하지 않는다."""
    with SessionLocal() as session:
        unique_names = {
            constraint.get("name")
            for constraint in inspect(session.bind).get_unique_constraints("instruments")
        }
    if "uq_instruments_krx_short_code" in unique_names:
        raise RuntimeError(
            "historical identity migration이 적용되지 않았습니다: "
            "alembic upgrade h2b3c4d5e6f7을 먼저 실행하세요"
        )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

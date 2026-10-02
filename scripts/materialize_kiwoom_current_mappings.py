#!/usr/bin/env python3
"""정확한 현재 KRX/Naver 증거에서만 Kiwoom provider mapping을 추가한다."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, session_scope
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.instrument_repository import InstrumentRepository
from app.services.kiwoom_mapping_materialization import (
    CurrentMappingCandidate,
    plan_kiwoom_current_mappings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        candidates = _candidates(session)
    plan = plan_kiwoom_current_mappings(candidates)
    report = {
        "candidate_count": len(candidates),
        "create_count": len(plan.creates),
        "unresolved_count": len(plan.unresolved),
        "creates": [
            {"instrument_id": row.instrument_id, "provider_symbol": row.provider_symbol, "valid_from": row.valid_from.isoformat()}
            for row in plan.creates
        ],
        "unresolved": plan.unresolved,
        "applied": args.apply,
    }
    if args.apply:
        with session_scope() as session:
            repository = InstrumentRepository(session)
            for row in plan.creates:
                repository.add_provider_symbol(
                    instrument_id=row.instrument_id,
                    provider="kiwoom",
                    provider_symbol=row.provider_symbol,
                    mapping_status="matched",
                    valid_from=row.valid_from,
                    evidence='{"basis":"exact_current_symbol_and_naver_mapping"}',
                )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"creates", "unresolved"}}, ensure_ascii=False, sort_keys=True))
    return 0


def _candidates(session) -> list[CurrentMappingCandidate]:
    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    symbol_rows: dict[int, list[Symbol]] = {}
    for row in session.scalars(select(Symbol).where(Symbol.instrument_id.is_not(None))):
        symbol_rows.setdefault(row.instrument_id, []).append(row)
    provider_rows: dict[tuple[int, str], list[ProviderSymbol]] = {}
    for row in session.scalars(select(ProviderSymbol).where(ProviderSymbol.mapping_status == "matched")):
        provider_rows.setdefault((row.instrument_id, row.provider), []).append(row)

    candidates: list[CurrentMappingCandidate] = []
    for instrument in instruments:
        symbols = symbol_rows.get(instrument.id, [])
        naver = provider_rows.get((instrument.id, "naver"), [])
        kiwoom = provider_rows.get((instrument.id, "kiwoom"), [])
        symbol = symbols[0] if len(symbols) == 1 else None
        naver_mapping = naver[0] if len(naver) == 1 else None
        candidates.append(CurrentMappingCandidate(
            instrument.id,
            instrument.krx_short_code,
            instrument.market,
            instrument.listed_at,
            instrument.listing_status,
            symbol.code if symbol else None,
            symbol.market if symbol else None,
            naver_mapping.provider_symbol if naver_mapping else None,
            bool(kiwoom),
        ))
    return candidates


if __name__ == "__main__":
    raise SystemExit(main())

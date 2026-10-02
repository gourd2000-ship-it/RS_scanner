#!/usr/bin/env python3
"""KRX 상장·상폐 CSV를 검토 후 import할 listing-event JSON으로 변환한다."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.instrument import Instrument
from app.services.krx_listing_csv import CanonicalInstrument, prepare_listing_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path, help="KRX CSV 파일; 반복 가능")
    parser.add_argument("--output", required=True, type=Path, help="import_listing_history.py 호환 JSON")
    parser.add_argument("--report", required=True, type=Path, help="unresolved/excluded 검토 JSON")
    args = parser.parse_args()

    files = [(str(path), path.read_bytes()) for path in sorted(args.input)]
    with SessionLocal() as session:
        identities = [
            CanonicalInstrument(
                row.id, row.krx_short_code, row.market, row.listed_at, row.delisted_at,
            )
            for row in session.scalars(select(Instrument).order_by(Instrument.id))
        ]
    prepared = prepare_listing_events(files, identities)
    document = {
        "events": prepared.events,
        "source_files": prepared.source_files,
        "unresolved": prepared.unresolved,
        "excluded": prepared.excluded,
    }
    report = {
        "input_file_count": len(files),
        "instrument_count": len(identities),
        "event_count": len(prepared.events),
        "unresolved_count": len(prepared.unresolved),
        "excluded": prepared.excluded,
        "source_files": prepared.source_files,
        "unresolved": prepared.unresolved,
    }
    _write_json(args.output, document)
    _write_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != "unresolved"}, ensure_ascii=False, sort_keys=True))
    return 0


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

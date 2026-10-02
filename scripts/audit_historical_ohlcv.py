"""현재 보유한 역사 OHLCV를 DB 변경 없이 전수 감사한다."""

import argparse
from datetime import date, datetime
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.validation.cleansing_assessment import assess_coverage
from app.services.validation.cleansing_policy import CleansingSelection
from app.services.validation.ohlcv_audit import audit_ohlcv


def main() -> None:
    parser = argparse.ArgumentParser(description="역사 OHLCV 읽기 전용 감사")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--selection-as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--observation-cutoff", required=True)
    parser.add_argument("--adjustment-policy", required=True, help="provider:adjustment_type")
    parser.add_argument("--market", choices=("KOSPI", "KOSDAQ"), action="append")
    parser.add_argument("--exclude-delisted", action="store_true", required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.observation_cutoff.replace("Z", "+00:00"))
    selection = CleansingSelection(
        start=args.start, end=args.end, selection_as_of=args.selection_as_of,
        observation_cutoff=cutoff, markets=tuple(sorted(set(args.market or ("KOSPI", "KOSDAQ")))),
    )
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                if connection.dialect.name == "postgresql":
                    connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                with Session(bind=connection, autoflush=False) as session:
                    result = audit_ohlcv(
                        session, selection=selection, adjustment_policy=args.adjustment_policy,
                        output_dir=args.output,
                    )
            assessment = assess_coverage(args.output)
            print(json.dumps({**result.__dict__, "segments": assessment},
                             ensure_ascii=False, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

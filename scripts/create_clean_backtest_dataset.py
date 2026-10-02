"""확인된 감사 범위를 고정 OHLCV 데이터셋으로 적재한다."""

import argparse
from datetime import date, datetime
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.clean_backtest_snapshot import create_clean_backtest_dataset
from app.services.validation.cleansing_policy import CleansingSelection
from app.services.validation.ohlcv_audit import QUALITY_RULE_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description="검증된 OHLCV 데이터셋 생성")
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--create", action="store_true", required=True)
    args = parser.parse_args()
    manifest = json.loads((args.audit_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((args.audit_dir / "summary.json").read_text(encoding="utf-8"))
    if summary.get("expected", 0) <= 0:
        parser.error("audit has no expected trading rows")
    if not manifest.get("exclude_delisted"):
        parser.error("audit must explicitly exclude delisted lifecycles")
    if manifest.get("quality_rule") != QUALITY_RULE_VERSION:
        parser.error("audit quality rule differs from the dataset builder")
    selection = CleansingSelection(
        start=date.fromisoformat(manifest["start"]),
        end=date.fromisoformat(manifest["end"]),
        selection_as_of=date.fromisoformat(manifest["selection_as_of"]),
        observation_cutoff=datetime.fromisoformat(manifest["observation_cutoff"]),
        markets=tuple(manifest["markets"]),
        exclude_delisted=True,
    )
    database_url = get_settings().database_url
    engine_options = {"pool_pre_ping": True}
    if database_url.startswith("postgresql"):
        engine_options["isolation_level"] = "REPEATABLE READ"
    engine = create_engine(database_url, **engine_options)
    try:
        with engine.begin() as connection:
            with Session(bind=connection, autoflush=False) as session:
                dataset = create_clean_backtest_dataset(
                    session, selection=selection, adjustment_policy=manifest["adjustment_policy"]
                )
                actual = dataset.manifest["coverage"]
                for status in ("valid", "missing", "invalid", "review_required", "non_tradable"):
                    if int(actual.get(status, 0)) != int(summary.get(status, 0)):
                        raise RuntimeError(f"audit changed before dataset creation: {status}")
                result = {
                    "dataset_id": dataset.dataset_id,
                    "manifest_hash": dataset.manifest_hash,
                    "coverage": dataset.manifest["coverage"],
                    "audit_dir": str(args.audit_dir),
                }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

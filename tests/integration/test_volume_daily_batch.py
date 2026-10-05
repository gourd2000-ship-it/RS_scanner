"""Daily adapter commits Volume lifecycle and separate checkpoint evidence."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.indicator import IndicatorCalculationRun, IndicatorSeries
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.services.batch.context import build_db_batch_context
from app.services.batch.volume_adapter import (
    calculate_daily_volume_sma50, completed_volume_outcome, record_volume_checkpoint,
)
from tests.integration.test_volume_calculation_postgres import pg_engine
from tests.unit.test_indicator_calculation_service import _observation
from tests.unit.test_volume_calculation_service import seed_history


def test_daily_volume_commits_incremental_failure_retry_and_rebuild(pg_engine, monkeypatch):
    settings = Settings(_env_file=None, volume_sma50_enabled=True,
                        volume_sma50_source_provider="kiwoom", volume_sma50_adjustment_type="1",
                        volume_sma50_allowed_parser_versions="kiwoom-v2")
    with Session(pg_engine) as session:
        instrument, symbol, mapping, dates = seed_history(session, 2)
        ids = instrument.id, symbol.id, mapping.id
        context = build_db_batch_context(session)
        job = context.crawl_job_repository.create_job("daily_full")
        context.job_id = job.id
        job_id = job.id
        context.checkpoint_repository.create_checkpoint(job_id, "ema", status="completed")
        first = calculate_daily_volume_sma50(context, target_date=dates[0], settings=settings)
        record_volume_checkpoint(context, first, settings=settings)
        assert first.outcome == "completed"
        session.commit()

    def fail(*_args, **_kwargs):
        raise RuntimeError("private provider detail")

    with monkeypatch.context() as failing:
        failing.setattr("app.services.indicators.volume_calculation_service.compute_volume_sma50", fail)
        with Session(pg_engine) as session:
            context = build_db_batch_context(session)
            context.job_id = job_id
            failed = calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings)
            record_volume_checkpoint(context, failed, settings=settings)
            assert failed.outcome == "failed" and failed.reason == "VolumeCalculationError"
            session.commit()

    with Session(pg_engine) as session:
        context = build_db_batch_context(session)
        context.job_id = job_id
        checkpoint = context.checkpoint_repository.get_checkpoint(job_id, "volume_sma50")
        assert checkpoint.status == "completed_with_errors"
        assert json.loads(checkpoint.step_metadata)["reason"] == "VolumeCalculationError"
        assert context.checkpoint_repository.get_checkpoint(job_id, "ema").status == "completed"
        assert completed_volume_outcome(context, settings=settings) is None
        retried = calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings)
        record_volume_checkpoint(context, retried, settings=settings)
        assert completed_volume_outcome(context, settings=settings) == retried
        session.commit()

    with Session(pg_engine) as session:
        instrument, symbol, mapping = (session.get(model, id_) for model, id_ in zip(
            (Instrument, Symbol, ProviderSymbol), ids, strict=True))
        _observation(session, instrument=instrument, symbol=symbol, mapping=mapping,
                     trade_date=dates[0], close="101", observed_at=datetime(2026, 1, 1, tzinfo=UTC))
        context = build_db_batch_context(session)
        context.job_id = job_id
        rebuilt = calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings)
        record_volume_checkpoint(context, rebuilt, settings=settings)
        session.commit()
        runs = session.scalars(select(IndicatorCalculationRun).order_by(IndicatorCalculationRun.id)).all()
        assert [(run.run_kind, run.status) for run in runs] == [
            ("backfill", "completed"), ("incremental", "failed"),
            ("incremental", "completed"), ("rebuild", "completed"),
        ]
        assert runs[0].generation_id == runs[1].generation_id == runs[2].generation_id
        assert runs[3].generation_id != runs[2].generation_id
        assert session.scalars(select(IndicatorSeries.indicator_kind)).all() == ["volume_sma"]

"""Daily adapter commits Volume lifecycle and separate checkpoint evidence."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.benchmark import Benchmark
from app.models.indicator import IndicatorCalculationRun, IndicatorSeries, IndicatorValue
from app.models.instrument import Instrument, ProviderSymbol
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.services.batch.context import build_db_batch_context
from app.services.batch.ema_adapter import calculate_daily_ema, record_ema_checkpoint
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
        first_run = session.scalar(select(IndicatorCalculationRun))
        assert first_run is not None and first_run.status == "completed"
        first_hashes = first_run.input_hash, first_run.result_hash
        assert completed_volume_outcome(context, settings=settings) == first
        mismatched_policy = settings.model_copy(update={"volume_sma50_adjustment_type": "2"})
        assert completed_volume_outcome(context, settings=mismatched_policy) is None
        repeated = calculate_daily_volume_sma50(context, target_date=dates[0], settings=settings)
        assert repeated.outcome == "completed"
        assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 1
        metadata = json.loads(context.checkpoint_repository.get_checkpoint(job_id, "volume_sma50").step_metadata)
        assert metadata["source_policy_hash"] and len(metadata["source_policy_hash"]) == 64
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
        incremental_run = session.scalar(select(IndicatorCalculationRun).where(
            IndicatorCalculationRun.run_kind == "incremental",
            IndicatorCalculationRun.status == "completed",
        ))
        assert incremental_run is not None
        incremental_hashes = incremental_run.input_hash, incremental_run.result_hash
        repeated_retry = calculate_daily_volume_sma50(context, target_date=dates[1], settings=settings)
        assert repeated_retry.outcome == "completed"
        assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 3
        assert (incremental_run.input_hash, incremental_run.result_hash) == incremental_hashes
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
        assert (runs[0].input_hash, runs[0].result_hash) == first_hashes
        assert (runs[2].input_hash, runs[2].result_hash) == incremental_hashes
        assert runs[3].input_hash != runs[2].input_hash
        assert runs[0].result_hash is not None and runs[2].result_hash is not None
        assert runs[0].generation_id == runs[1].generation_id == runs[2].generation_id
        assert runs[3].generation_id != runs[2].generation_id
        assert session.scalars(select(IndicatorSeries.indicator_kind)).all() == ["volume_sma"]


def test_daily_volume_skips_when_policy_has_no_target_date_observation(pg_engine):
    settings = Settings(_env_file=None, volume_sma50_enabled=True,
                        volume_sma50_source_provider="kiwoom", volume_sma50_adjustment_type="1",
                        volume_sma50_allowed_parser_versions="kiwoom-v2")
    with Session(pg_engine) as session:
        _, _, _, dates = seed_history(session, 1)
        context = build_db_batch_context(session)
        job = context.crawl_job_repository.create_job("daily_full")
        context.job_id = job.id

        outcome = calculate_daily_volume_sma50(
            context, target_date=dates[0] + timedelta(days=1), settings=settings,
        )
        record_volume_checkpoint(context, outcome, settings=settings)
        session.commit()

        assert outcome.outcome == "skipped"
        assert outcome.reason == "target_date_observations_missing"
        checkpoint = context.checkpoint_repository.get_checkpoint(job.id, "volume_sma50")
        assert checkpoint.status == "completed_with_errors"
        assert json.loads(checkpoint.step_metadata)["reason"] == "target_date_observations_missing"
        assert session.scalar(select(func.count()).select_from(IndicatorSeries)) == 0
        assert session.scalar(select(func.count()).select_from(IndicatorCalculationRun)) == 0
        assert session.scalar(select(func.count()).select_from(IndicatorValue)) == 0


@pytest.mark.parametrize("selection_step", ["expected_trade_dates", "eligible_instrument_ids"])
def test_input_sql_error_keeps_daily_rs_ema_and_volume_failure_committable(pg_engine, monkeypatch, selection_step):
    settings = Settings(
        _env_file=None,
        ema_enabled=True, ema_source_provider="kiwoom", ema_adjustment_type="1",
        ema_allowed_parser_versions="kiwoom-v2",
        volume_sma50_enabled=True, volume_sma50_source_provider="kiwoom",
        volume_sma50_adjustment_type="1", volume_sma50_allowed_parser_versions="kiwoom-v2",
    )
    with Session(pg_engine) as session:
        _, symbol, _, dates = seed_history(session, 2)
        benchmark = Benchmark(benchmark_code="KOSPI", name="KOSPI", market="KOSPI")
        session.add(benchmark)
        session.flush()
        score = RsScore(
            symbol_id=symbol.id, benchmark_id=benchmark.id, trade_date=dates[-1], market="KOSPI",
            return_3m=Decimal("0.1"), return_6m=Decimal("0.1"), return_9m=Decimal("0.1"),
            return_12m=Decimal("0.1"), relative_return_score=Decimal("0.1"),
            rs_percentile=Decimal("1"), rs_rating=99, rank_in_market=1,
        )
        session.add(score)
        context = build_db_batch_context(session)
        job_id = context.crawl_job_repository.create_job("daily_full").id
        context.job_id = job_id
        context.checkpoint_repository.create_checkpoint(job_id, "rs", status="completed")
        ema = calculate_daily_ema(context, target_date=dates[-1], settings=settings)
        assert ema.outcome == "completed" and ema.processed == 1
        record_ema_checkpoint(context, ema)
        ema_run_id = session.scalar(select(IndicatorCalculationRun.id))
        score_id = score.id

        def sql_error(context, **_kwargs):
            # PostgreSQL aborts the active transaction on this real statement error.
            context.session.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(f"app.services.batch.volume_adapter.{selection_step}", sql_error)
        failed = calculate_daily_volume_sma50(context, target_date=dates[-1], settings=settings)
        assert failed.outcome == "failed" and failed.reason == "DataError"
        record_volume_checkpoint(context, failed, settings=settings)
        session.commit()

    with Session(pg_engine) as session:
        assert session.get(RsScore, score_id).rs_rating == 99
        ema_run = session.get(IndicatorCalculationRun, ema_run_id)
        assert ema_run.status == "completed" and ema_run.result_hash is not None
        assert session.scalar(select(func.count()).select_from(IndicatorValue).where(
            IndicatorValue.calculation_run_id == ema_run_id)) == 8
        context = build_db_batch_context(session)
        for step in ("rs", "ema"):
            assert context.checkpoint_repository.get_checkpoint(job_id, step).status == "completed"
        checkpoint = context.checkpoint_repository.get_checkpoint(job_id, "volume_sma50")
        assert checkpoint.status == "completed_with_errors" and checkpoint.items_failed == 1
        assert json.loads(checkpoint.step_metadata) == {"outcome": "failed", "reason": "DataError"}
        assert session.scalars(select(IndicatorSeries.indicator_kind)).all() == ["ema"]

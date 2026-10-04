from types import SimpleNamespace

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.core.config import Settings
from app.models.data_quality import PriceObservation
from app.models.indicator import IndicatorCalculationRun
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.memory_batch_checkpoint_repository import MemoryBatchCheckpointRepository
from app.repositories.indicator_repository import IndicatorRepository
from app.services.batch.ema_adapter import (
    EmaBatchOutcome,
    calculate_daily_ema,
    record_ema_checkpoint,
)


def test_ema_checkpoint_records_a_skipped_enabled_step_as_completed_with_errors():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=17)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.skipped("validation_gate_blocked"),
    )

    checkpoint = repository.get_checkpoint(17, "ema")
    assert checkpoint is not None
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_failed == 1
    assert checkpoint.step_metadata == (
        '{"outcome": "skipped", "reason": "validation_gate_blocked"}'
    )
    assert not repository.is_step_completed(17, "ema")


def test_ema_checkpoint_records_a_failed_step_without_raising():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=18)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.failure(processed=2, failed=1, reason="RuntimeError"),
    )

    checkpoint = repository.get_checkpoint(18, "ema")
    assert checkpoint is not None
    assert checkpoint.status == "completed_with_errors"
    assert checkpoint.items_processed == 2
    assert checkpoint.items_failed == 1
    assert checkpoint.step_metadata == (
        '{"outcome": "failed", "reason": "RuntimeError"}'
    )


def test_completed_ema_checkpoint_is_resumable_as_a_completed_step():
    repository = MemoryBatchCheckpointRepository()
    context = SimpleNamespace(checkpoint_repository=repository, job_id=19)

    record_ema_checkpoint(
        context,
        EmaBatchOutcome.completed(processed=2),
    )

    assert repository.is_step_completed(19, "ema")


def test_daily_ema_accepts_successive_observations_after_the_first_run():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="EMA-T5", name="EMA T5", market="KOSPI",
            security_type="stock", listing_status="listed",
        )
        symbol = Symbol(code="EMA-T5", name="EMA T5", market="KOSPI")
        session.add_all((instrument, symbol))
        session.flush()
        mapping = ProviderSymbol(
            instrument_id=instrument.id, provider="kiwoom", provider_symbol="EMA-T5",
            valid_from=date(2025, 1, 1), mapping_status="matched",
        )
        session.add(mapping)
        session.flush()

        first_day = date(2025, 1, 2)
        _add_ema_observation(
            session, instrument, symbol, mapping, first_day,
            observed_at=datetime(2025, 1, 2, 18, tzinfo=UTC), close="100",
        )
        context = SimpleNamespace(session=session)
        settings = Settings(ema_enabled=True)

        first = calculate_daily_ema(context, target_date=first_day, settings=settings)
        assert first == EmaBatchOutcome.completed(processed=1)

        second_day = date(2025, 1, 3)
        _add_ema_observation(
            session, instrument, symbol, mapping, second_day,
            observed_at=datetime(2025, 1, 3, 18, tzinfo=UTC), close="101",
        )
        second = calculate_daily_ema(context, target_date=second_day, settings=settings)

        assert second == EmaBatchOutcome.completed(processed=1)
        assert session.scalars(
            select(IndicatorCalculationRun.run_kind).order_by(IndicatorCalculationRun.id)
        ).all() == ["backfill", "incremental"]
    engine.dispose()


def _add_ema_observation(session, instrument, symbol, mapping, trade_date, *, observed_at, close):
    observation = PriceObservation(
        symbol_id=symbol.id, trade_date=trade_date,
        open=Decimal(close), high=Decimal(close) + 1, low=Decimal(close) - 1,
        close=Decimal(close), volume=1000, change_rate=Decimal("0"),
        provider="kiwoom", parser_version="kiwoom-history-v1", adjustment_type="1",
        payload_hash=f"{trade_date.day:064x}", observed_at=observed_at,
    )
    session.add(observation)
    session.flush()
    IndicatorRepository(session).create_identity_snapshot(
        price_observation_id=observation.id,
        instrument_id=instrument.id,
        provider_symbol_mapping_id=mapping.id,
        provider="kiwoom",
        provider_symbol="EMA-T5",
        mapping_status="matched",
        mapping_valid_from=date(2025, 1, 1),
        mapping_valid_to=None,
        resolver_version="test-resolver",
        resolved_at=observed_at,
    )

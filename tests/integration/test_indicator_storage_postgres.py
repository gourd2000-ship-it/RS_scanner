"""PostgreSQL trigger coverage for immutable EMA evidence."""

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.data_quality import PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputSnapshot,
    IndicatorValue,
    PriceObservationIdentitySnapshot,
)
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.indicator_repository import IndicatorRepository
from app.services.indicators import (
    EmaInputRow,
    EmaSourcePolicy,
    IdentitySnapshot,
    compute_ema,
)


def _policy() -> EmaSourcePolicy:
    return EmaSourcePolicy(
        provider="kiwoom",
        adjustment_type="1",
        allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
    )


def _assert_rejected(session: Session, statement: object) -> None:
    savepoint = session.begin_nested()
    with pytest.raises(DBAPIError):
        session.execute(statement)
    savepoint.rollback()


def test_indicator_storage_on_isolated_postgres_rejects_immutable_history_mutation():
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test",
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        try:
            connection = engine.connect()
        except SQLAlchemyError as exc:
            pytest.skip(f"isolated PostgreSQL unavailable: {type(exc).__name__}")
        with connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, autoflush=False) as session:
                    instrument = Instrument(
                        krx_short_code="EMAPG", name="EMA 검증", market="KOSPI", security_type="stock",
                        listing_status="listed",
                    )
                    symbol = Symbol(code="EMAPG", name="EMA 검증", market="KOSPI")
                    session.add_all((instrument, symbol))
                    session.flush()
                    symbol.instrument_id = instrument.id
                    mapping = ProviderSymbol(
                        instrument_id=instrument.id, provider="kiwoom", provider_symbol="EMAPG",
                        valid_from=date(2020, 1, 1), mapping_status="matched",
                    )
                    observation = PriceObservation(
                        symbol_id=symbol.id, trade_date=date(2024, 1, 2),
                        open=Decimal(100), high=Decimal(101), low=Decimal(99), close=Decimal(100),
                        volume=1000, change_rate=Decimal(0), provider="kiwoom", parser_version="kiwoom-v2",
                        adjustment_type="1", payload_hash="a" * 64,
                        observed_at=datetime(2024, 1, 2, tzinfo=UTC),
                    )
                    session.add_all((mapping, observation))
                    session.flush()

                    repository = IndicatorRepository(session)
                    identity = repository.create_identity_snapshot(
                        price_observation_id=observation.id, instrument_id=instrument.id,
                        provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="EMAPG",
                        mapping_status="matched", mapping_valid_from=date(2020, 1, 1), mapping_valid_to=None,
                        resolver_version="provider-symbol-resolver-v1",
                        resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
                    )
                    series = repository.create_series(instrument_id=instrument.id, policy=_policy())
                    generation = repository.create_generation(series_id=series.id, generation=1)
                    run = repository.create_run(
                        generation=generation, run_kind="backfill",
                        input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
                    )
                    row = EmaInputRow(
                        trade_date=date(2024, 1, 2), instrument_id=instrument.id, symbol_id=symbol.id,
                        observation_id=observation.id,
                        identity=IdentitySnapshot(
                            snapshot_id=identity.id, instrument_id=instrument.id, provider="kiwoom",
                            provider_symbol="EMAPG", provider_mapping_id=mapping.id, mapping_status="matched",
                            valid_from=date(2020, 1, 1), valid_to=None,
                            resolver_version="provider-symbol-resolver-v1",
                            resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
                        ),
                        provider="kiwoom", provider_symbol="EMAPG", adjustment_type="1",
                        parser_version="kiwoom-v2", close=Decimal(100), volume=1000,
                        observed_at=datetime(2024, 1, 2, tzinfo=UTC), payload_hash="a" * 64,
                        source_policy=_policy(),
                    )
                    result = compute_ema((row,))
                    inputs, values = repository.append_result(run=run, input_rows=(row,), result=result)
                    session.execute(
                        update(IndicatorCalculationRun)
                        .where(IndicatorCalculationRun.id == run.id)
                        .values(
                            status="completed", input_hash=result.input_hash, result_hash=result.result_hash,
                            input_count=len(inputs), result_count=len(values),
                            completed_at=datetime(2024, 1, 3, tzinfo=UTC),
                        )
                    )
                    session.flush()

                    _assert_rejected(
                        session,
                        update(PriceObservationIdentitySnapshot)
                        .where(PriceObservationIdentitySnapshot.id == identity.id)
                        .values(provider_symbol="altered"),
                    )
                    _assert_rejected(
                        session,
                        delete(PriceObservationIdentitySnapshot)
                        .where(PriceObservationIdentitySnapshot.id == identity.id),
                    )
                    _assert_rejected(
                        session,
                        update(IndicatorInputSnapshot)
                        .where(IndicatorInputSnapshot.id == inputs[0].id)
                        .values(prefix_hash="b" * 64),
                    )
                    _assert_rejected(
                        session,
                        delete(IndicatorValue).where(IndicatorValue.id == values[0].id),
                    )
                    _assert_rejected(
                        session,
                        delete(IndicatorCalculationRun).where(IndicatorCalculationRun.id == run.id),
                    )

                    other_series = repository.create_series(
                        instrument_id=instrument.id,
                        policy=EmaSourcePolicy(
                            provider="kiwoom",
                            adjustment_type="1",
                            allowed_parser_versions=("kiwoom-v2",),
                            observation_cutoff=datetime(2024, 2, 2, tzinfo=UTC),
                        ),
                    )
                    wrong_parent = IndicatorGeneration(
                        series_id=other_series.id,
                        generation=1,
                        parent_generation_id=generation.id,
                        status="building",
                    )
                    parent_savepoint = session.begin_nested()
                    session.add(wrong_parent)
                    with pytest.raises(DBAPIError):
                        session.flush()
                    parent_savepoint.rollback()

                    incomplete_generation = repository.create_generation(
                        series_id=series.id,
                        generation=2,
                    )
                    incomplete_run = repository.create_run(
                        generation=incomplete_generation,
                        run_kind="rebuild",
                        input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
                    )
                    incomplete_inputs = repository.append_inputs(
                        run=incomplete_run,
                        rows=(row,),
                        prefix_hashes=result.prefix_hashes,
                    )
                    _assert_rejected(
                        session,
                        update(IndicatorCalculationRun)
                        .where(IndicatorCalculationRun.id == incomplete_run.id)
                        .values(
                            status="completed",
                            input_hash=result.input_hash,
                            result_hash=result.result_hash,
                            input_count=len(incomplete_inputs),
                            result_count=0,
                            completed_at=datetime(2024, 1, 3, tzinfo=UTC),
                        ),
                    )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()

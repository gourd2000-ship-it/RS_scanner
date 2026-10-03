"""EMA persistence keeps contract snapshots and blocks mutable history paths."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- load all metadata
from app.core.base import Base
from app.models.data_quality import PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorSeries,
    IndicatorValue,
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


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed(session: Session):
    instrument = Instrument(
        krx_short_code="005930", name="삼성전자", market="KOSPI", security_type="stock",
        listing_status="listed",
    )
    symbol = Symbol(code="005930", name="삼성전자", market="KOSPI", instrument_id=None)
    session.add_all((instrument, symbol))
    session.flush()
    symbol.instrument_id = instrument.id
    mapping = ProviderSymbol(
        instrument_id=instrument.id, provider="kiwoom", provider_symbol="005930",
        valid_from=date(2020, 1, 1), valid_to=None, mapping_status="matched",
    )
    observation = PriceObservation(
        symbol_id=symbol.id, trade_date=date(2024, 1, 2), open=Decimal(100), high=Decimal(101),
        low=Decimal(99), close=Decimal(100), volume=1000, change_rate=Decimal(0),
        provider="kiwoom", parser_version="kiwoom-v2", adjustment_type="1", payload_hash="a" * 64,
        observed_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    session.add_all((mapping, observation))
    session.flush()
    return instrument, symbol, mapping, observation


def _policy() -> EmaSourcePolicy:
    return EmaSourcePolicy(
        provider="kiwoom", adjustment_type="1", allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
    )


def test_repository_materializes_contract_snapshots_and_rejects_completed_run_writes(session: Session):
    instrument, symbol, mapping, observation = _seed(session)
    repository = IndicatorRepository(session)
    identity = repository.create_identity_snapshot(
        price_observation_id=observation.id, instrument_id=instrument.id,
        provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="005930",
        mapping_status="matched", mapping_valid_from=date(2020, 1, 1), mapping_valid_to=None,
        resolver_version="provider-symbol-resolver-v1", resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    series = repository.create_series(instrument_id=instrument.id, policy=_policy())
    generation = repository.create_generation(series_id=series.id, generation=1)
    run = repository.create_run(
        generation=generation, run_kind="backfill", input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
    )
    row = EmaInputRow(
        trade_date=date(2024, 1, 2), instrument_id=instrument.id, symbol_id=symbol.id,
        observation_id=observation.id,
        identity=IdentitySnapshot(
            snapshot_id=identity.id, instrument_id=instrument.id, provider="kiwoom", provider_symbol="005930",
            provider_mapping_id=mapping.id, mapping_status="matched", valid_from=date(2020, 1, 1),
            valid_to=None, resolver_version="provider-symbol-resolver-v1",
            resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
        ),
        provider="kiwoom", provider_symbol="005930", adjustment_type="1", parser_version="kiwoom-v2",
        close=Decimal(100), volume=1000, observed_at=datetime(2024, 1, 2, tzinfo=UTC),
        payload_hash="a" * 64, source_policy=_policy(),
    )
    result = compute_ema((row,))
    inputs, values = repository.append_result(run=run, input_rows=(row,), result=result)

    assert inputs[0].price_observation_identity_snapshot_id == identity.id
    assert inputs[0].provider_symbol_mapping_id == mapping.id
    assert inputs[0].row_hash == result.row_fingerprints[0]
    assert len(values) == 4
    assert {value.period for value in values} == {5, 20, 50, 200}

    run.status = "completed"
    run.input_hash = result.input_hash
    run.result_hash = result.result_hash
    run.input_count = len(inputs)
    run.result_count = len(values)
    run.completed_at = datetime(2024, 1, 3, tzinfo=UTC)
    session.flush()
    with pytest.raises(ValueError, match="immutable"):
        repository.append_values(run=run, values=result.values)


def test_identity_snapshot_is_one_immutable_record_per_observation(session: Session):
    instrument, _, mapping, observation = _seed(session)
    repository = IndicatorRepository(session)
    repository.create_identity_snapshot(
        price_observation_id=observation.id, instrument_id=instrument.id,
        provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="005930",
        mapping_status="matched", mapping_valid_from=date(2020, 1, 1), mapping_valid_to=None,
        resolver_version="provider-symbol-resolver-v1", resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    with pytest.raises(IntegrityError):
        repository.create_identity_snapshot(
            price_observation_id=observation.id, instrument_id=instrument.id,
            provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="005930",
            mapping_status="matched", mapping_valid_from=date(2020, 1, 1), mapping_valid_to=None,
            resolver_version="provider-symbol-resolver-v1", resolved_at=datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_current_generation_accepts_a_new_incremental_run(session: Session):
    instrument, _, _, _ = _seed(session)
    repository = IndicatorRepository(session)
    series = repository.create_series(instrument_id=instrument.id, policy=_policy())
    current = repository.create_generation(series_id=series.id, generation=1, status="current")

    incremental = repository.create_run(
        generation=current, run_kind="incremental",
        input_cutoff=datetime(2024, 2, 1, tzinfo=UTC), range_start=date(2024, 1, 3),
        range_end=date(2024, 1, 3),
    )

    assert incremental.generation_id == current.id
    assert incremental.status == "running"

    building = repository.create_generation(series_id=series.id, generation=2)
    with pytest.raises(ValueError, match="current generation"):
        repository.create_run(
            generation=building, run_kind="incremental",
            input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
        )


def test_model_constraints_allow_one_running_run_and_only_supported_periods(session: Session):
    instrument, _, _, _ = _seed(session)
    repository = IndicatorRepository(session)
    series = repository.create_series(instrument_id=instrument.id, policy=_policy())
    generation = repository.create_generation(series_id=series.id, generation=1)
    run = repository.create_run(
        generation=generation, run_kind="backfill", input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
    )
    session.commit()

    second_generation = IndicatorGeneration(series_id=series.id, generation=2, status="building")
    session.add(second_generation)
    session.flush()
    session.add(IndicatorCalculationRun(
        generation_id=second_generation.id, series_id=series.id, run_kind="rebuild", status="running",
        input_cutoff=datetime(2024, 2, 1, tzinfo=UTC),
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    # Use a clean session state to prove the database, rather than repository
    # validation, rejects an unsupported EMA period.
    with Session(session.bind) as clean_session:
        generation = clean_session.get(IndicatorGeneration, generation.id)
        run = clean_session.get(IndicatorCalculationRun, run.id)
        clean_session.add(IndicatorValue(
            calculation_run_id=run.id, generation_id=generation.id, period=7, trade_date=date(2024, 1, 2),
            value=Decimal(100), status="available", reason_code=None, available_observations=7,
            input_prefix_hash="b" * 64,
        ))
        with pytest.raises(IntegrityError):
            clean_session.flush()


def test_model_constraints_reject_duplicate_policy_and_invalid_generation_number(session: Session):
    instrument, _, _, _ = _seed(session)
    repository = IndicatorRepository(session)
    series = repository.create_series(instrument_id=instrument.id, policy=_policy())
    session.commit()
    with pytest.raises(IntegrityError):
        repository.create_series(instrument_id=instrument.id, policy=_policy())

    session.rollback()
    series = session.get(IndicatorSeries, series.id)
    assert series is not None
    session.add(IndicatorGeneration(series_id=series.id, generation=0, status="building"))
    with pytest.raises(IntegrityError):
        session.flush()

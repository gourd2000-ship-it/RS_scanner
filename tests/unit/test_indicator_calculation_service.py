"""EMA observation selection and generation-transition regression coverage."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register metadata
from app.core.base import Base
from app.models.data_quality import OhlcCorrection, PriceObservation, ValidationCase, ValidationRun
from app.models.indicator import IndicatorCalculationRun, IndicatorGeneration, PriceObservationIdentitySnapshot
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.indicator_repository import IndicatorRepository
from app.services.indicators.calculation_service import EmaCalculationService
from app.services.indicators.contracts import EmaInputStatus, EmaSourcePolicy, InputReasonCode
from app.services.indicators.input_selector import EmaInputSelector


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _policy() -> EmaSourcePolicy:
    return EmaSourcePolicy(
        provider="kiwoom", adjustment_type="1", allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _seed(session: Session):
    instrument = Instrument(
        krx_short_code="EMAT3", name="EMA T3", market="KOSPI", security_type="stock", listing_status="listed",
    )
    symbol = Symbol(code="EMAT3", name="EMA T3", market="KOSPI")
    session.add_all((instrument, symbol))
    session.flush()
    mapping = ProviderSymbol(
        instrument_id=instrument.id, provider="kiwoom", provider_symbol="EMAT3",
        valid_from=date(2020, 1, 1), mapping_status="matched",
    )
    session.add(mapping)
    session.flush()
    return instrument, symbol, mapping


def _observation(
    session: Session,
    *,
    instrument: Instrument,
    symbol: Symbol,
    mapping: ProviderSymbol,
    trade_date: date,
    close: str,
    observed_at: datetime,
) -> PriceObservation:
    row = PriceObservation(
        symbol_id=symbol.id, trade_date=trade_date, open=Decimal(close), high=Decimal(close) + 1,
        low=Decimal(close) - 1, close=Decimal(close), volume=1000, change_rate=Decimal(0),
        provider="kiwoom", parser_version="kiwoom-v2", adjustment_type="1",
        payload_hash=f"{trade_date.day:064x}", observed_at=observed_at,
    )
    session.add(row)
    session.flush()
    IndicatorRepository(session).create_identity_snapshot(
        price_observation_id=row.id, instrument_id=instrument.id,
        provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="EMAT3",
        mapping_status="matched", mapping_valid_from=date(2020, 1, 1), mapping_valid_to=None,
        resolver_version="resolver-v1", resolved_at=observed_at,
    )
    return row


def test_selector_uses_identity_snapshots_and_records_review_and_correction_reasons(session: Session):
    instrument, symbol, mapping = _seed(session)
    day = date(2024, 1, 2)
    first = _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=day,
        close="100", observed_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    second = _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=day,
        close="101", observed_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    next_day = date(2024, 1, 3)
    corrected = _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=next_day,
        close="102", observed_at=datetime(2024, 1, 3, tzinfo=UTC),
    )
    session.add(OhlcCorrection(
        symbol_id=symbol.id, trade_date=next_day, field_name="close", original_value="102",
        corrected_value="not-a-number", reason_code="test", status="APPROVED",
    ))
    open_day = date(2024, 1, 4)
    _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=open_day,
        close="103", observed_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
    validation_run = ValidationRun(validator_version="test", mode="report_only")
    session.add(validation_run)
    session.flush()
    session.add(ValidationCase(
        validation_run_id=validation_run.id, subject_type="daily_price", symbol_id=symbol.id,
        trade_date=open_day, rule_id="test", severity="warning", reason_code="test",
        case_status="open", validator_version="test",
    ))
    session.flush()

    rows = EmaInputSelector(session).select_rows(
        instrument_id=instrument.id, trade_dates=(day, next_day, open_day, date(2024, 1, 5)), policy=_policy(),
    )

    assert rows[0].observation_id == second.id
    assert rows[0].input_status is EmaInputStatus.REVIEW_REQUIRED
    assert rows[0].reason_code is InputReasonCode.CONFLICTING_OBSERVATIONS
    assert rows[1].observation_id == corrected.id
    assert rows[1].reason_code is InputReasonCode.INVALID_APPROVED_CORRECTION
    assert rows[2].reason_code is InputReasonCode.OPEN_VALIDATION_CASE
    assert rows[3].reason_code is InputReasonCode.MISSING_SELECTED_SOURCE
    # The selector did not infer ownership through the current Symbol link.
    assert first.symbol_id == symbol.id and symbol.instrument_id is None


def test_calculation_full_incremental_idempotent_rebuild_and_cleanup_candidates(session: Session):
    instrument, symbol, mapping = _seed(session)
    start = date(2024, 1, 2)
    dates = tuple(start + timedelta(days=index) for index in range(2))
    for index, day in enumerate(dates):
        _observation(
            session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=day,
            close=str(100 + index), observed_at=datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=index),
        )
    service = EmaCalculationService(session)
    first = service.calculate(instrument_id=instrument.id, trade_dates=dates, policy=_policy())
    assert first.run_kind == "backfill"
    assert session.get(IndicatorGeneration, first.generation_id).status == "current"
    assert session.scalar(select(IndicatorCalculationRun.result_count).where(IndicatorCalculationRun.id == first.run_id)) == 8

    third_date = start + timedelta(days=2)
    _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=third_date,
        close="102", observed_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
    incremental = service.calculate(
        instrument_id=instrument.id, trade_dates=(*dates, third_date), policy=_policy(),
    )
    assert incremental.run_kind == "incremental"
    assert incremental.generation_id == first.generation_id
    assert session.get(IndicatorCalculationRun, incremental.run_id).result_count == 4
    unchanged = service.calculate(
        instrument_id=instrument.id, trade_dates=(*dates, third_date), policy=_policy(),
    )
    assert unchanged.reused is True and unchanged.run_id == incremental.run_id

    # A later immutable observation changes historical input selection, so a
    # complete replacement generation is promoted only after all rows exist.
    _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=dates[0],
        close="99", observed_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    rebuilt = service.calculate(
        instrument_id=instrument.id, trade_dates=(*dates, third_date), policy=_policy(),
    )
    old_generation = session.get(IndicatorGeneration, first.generation_id)
    assert rebuilt.run_kind == "rebuild"
    assert old_generation.status == "superseded"
    assert session.get(IndicatorGeneration, rebuilt.generation_id).status == "current"
    assert session.get(IndicatorCalculationRun, rebuilt.run_id).result_count == 12

    old_generation.superseded_at = datetime.now(UTC) - timedelta(days=31)
    assert [candidate.generation_id for candidate in service.cleanup_candidates()] == [old_generation.id]
    assert service.cleanup_candidates(referenced_generation_ids=(old_generation.id,)) == ()


def test_failed_building_generation_never_replaces_current_generation(session: Session):
    instrument, symbol, mapping = _seed(session)
    day = date(2024, 1, 2)
    _observation(
        session, instrument=instrument, symbol=symbol, mapping=mapping, trade_date=day,
        close="100", observed_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    service = EmaCalculationService(session)
    complete = service.calculate(instrument_id=instrument.id, trade_dates=(day,), policy=_policy())
    repository = IndicatorRepository(session)
    building = repository.create_generation(series_id=complete.series_id, generation=2, status="building")
    run = repository.create_run(
        generation=building, run_kind="rebuild", input_cutoff=_policy().observation_cutoff,
    )
    service.fail_run(run.id, failure_reason="test failure")

    assert session.get(IndicatorGeneration, complete.generation_id).status == "current"
    assert session.get(IndicatorGeneration, building.id).status == "failed"
    assert session.get(IndicatorCalculationRun, run.id).status == "failed"

"""Read-only EMA backfill planning and idempotent operator application."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 -- register model metadata
from app.core.base import Base
from app.models.data_quality import PriceObservation
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorInputSnapshot,
    IndicatorSeries,
    IndicatorValue,
)
from app.models.instrument import Instrument, ProviderSymbol
from app.models.symbol import Symbol
from app.repositories.indicator_repository import IndicatorRepository
from app.services.indicators.backfill import EmaHistoricalBackfillService, EmaHistoricalBackfillRequest
from app.services.indicators.contracts import EmaSourcePolicy
import scripts.backfill_ema as backfill_cli


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _policy() -> EmaSourcePolicy:
    return EmaSourcePolicy(
        provider="kiwoom",
        adjustment_type="1",
        allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _seed(session: Session) -> tuple[Instrument, tuple[date, ...]]:
    instrument = Instrument(
        krx_short_code="EMABF",
        name="EMA backfill",
        market="KOSPI",
        security_type="stock",
        listing_status="listed",
    )
    symbol = Symbol(code="EMABF", name="EMA backfill", market="KOSPI")
    session.add_all((instrument, symbol))
    session.flush()
    mapping = ProviderSymbol(
        instrument_id=instrument.id,
        provider="kiwoom",
        provider_symbol="EMABF",
        valid_from=date(2020, 1, 1),
        mapping_status="matched",
    )
    session.add(mapping)
    session.flush()
    dates = tuple(date(2024, 1, 2) + timedelta(days=index) for index in range(5))
    for index, trade_date in enumerate(dates):
        close = Decimal(100 + index)
        observation = PriceObservation(
            symbol_id=symbol.id,
            trade_date=trade_date,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1000,
            change_rate=Decimal(0),
            provider="kiwoom",
            parser_version="kiwoom-v2",
            adjustment_type="1",
            payload_hash=f"{index + 1:064x}",
            observed_at=datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=index),
        )
        session.add(observation)
        session.flush()
        IndicatorRepository(session).create_identity_snapshot(
            price_observation_id=observation.id,
            instrument_id=instrument.id,
            provider_symbol_mapping_id=mapping.id,
            provider="kiwoom",
            provider_symbol="EMABF",
            mapping_status="matched",
            mapping_valid_from=date(2020, 1, 1),
            mapping_valid_to=None,
            resolver_version="resolver-v1",
            resolved_at=observation.observed_at,
        )
    session.commit()
    return instrument, dates


def _request(instrument_id: int, dates: tuple[date, ...]) -> EmaHistoricalBackfillRequest:
    return EmaHistoricalBackfillRequest(
        start=dates[0],
        end=dates[-1],
        policy=_policy(),
        instrument_ids=(instrument_id,),
        chunk_size=1,
    )


def _service(session: Session) -> EmaHistoricalBackfillService:
    return EmaHistoricalBackfillService(session, is_trading_day=lambda _: True)


def _counts(session: Session) -> tuple[int, int, int, int]:
    return tuple(
        session.scalar(select(func.count(model.id)))
        for model in (IndicatorSeries, IndicatorCalculationRun, IndicatorInputSnapshot, IndicatorValue)
    )


def test_dry_run_plan_is_read_only_and_reports_exact_hashes_and_availability(session: Session):
    instrument, dates = _seed(session)
    before = _counts(session)

    plan = _service(session).plan(_request(instrument.id, dates))
    report = plan.report()

    assert _counts(session) == before == (0, 0, 0, 0)
    assert report["report_hash"] == plan.report()["report_hash"]
    assert report["counts"] == {
        "targets": 1,
        "input_rows": 5,
        "indicator_value_rows": 20,
        "warming_up_rows": 19,
        "data_unavailable_rows": 0,
        "available_rows": 1,
        "rebuild_targets": 0,
    }
    target = report["targets"][0]
    assert target["first_available"] == {"5": "2024-01-06", "20": None, "50": None, "200": None}
    assert target["input_hash"] and target["result_hash"]
    assert report["estimate"]["input_snapshot_rows"] == 5
    assert report["estimate"]["indicator_value_rows"] == 20


def test_apply_rerun_and_resume_keep_completed_runs_immutable(session: Session):
    instrument, dates = _seed(session)
    service = _service(session)
    request = _request(instrument.id, dates)
    plan = service.plan(request)

    first = service.apply(plan)
    first_counts = _counts(session)
    assert first.created == 1
    assert first.reused == 0
    assert first_counts == (1, 1, 5, 20)
    first_run = session.scalar(select(IndicatorCalculationRun))
    assert first_run is not None and first_run.status == "completed"
    hashes = (first_run.input_hash, first_run.result_hash)

    rerun = service.apply(service.plan(request))
    resumed = service.apply(service.plan(request), resume=True)

    assert rerun.reused == 1 and rerun.created == 0
    assert resumed.reused == 1 and resumed.created == 0
    assert _counts(session) == first_counts
    completed = session.scalar(select(IndicatorCalculationRun))
    assert completed is not None and (completed.input_hash, completed.result_hash) == hashes
    assert first.report_hash == plan.report()["report_hash"]
    assert rerun.report_hash == resumed.report_hash


def test_changed_historical_input_is_a_rebuild_target_and_creates_new_immutable_generation(session: Session):
    instrument, dates = _seed(session)
    service = _service(session)
    request = _request(instrument.id, dates)
    service.apply(service.plan(request))

    first_observation = session.scalar(
        select(PriceObservation).where(PriceObservation.trade_date == dates[0])
    )
    assert first_observation is not None
    first_observation.close = Decimal("99")
    first_observation.open = Decimal("99")
    first_observation.high = Decimal("100")
    first_observation.low = Decimal("98")
    session.commit()

    revised_plan = service.plan(request)
    assert revised_plan.report()["counts"]["rebuild_targets"] == 1
    applied = service.apply(revised_plan, resume=True)

    assert applied.created == 1
    assert session.scalar(select(func.count(IndicatorCalculationRun.id))) == 2


def test_cli_default_dry_run_serializes_report_without_database_mutation(session: Session, monkeypatch):
    instrument, dates = _seed(session)
    before = _counts(session)
    monkeypatch.setattr(backfill_cli, "SessionLocal", sessionmaker(bind=session.bind))
    args = backfill_cli.build_parser().parse_args([
        "--start", dates[0].isoformat(),
        "--end", dates[-1].isoformat(),
        "--provider", "kiwoom",
        "--adjustment-type", "1",
        "--parser-version", "kiwoom-v2",
        "--observation-cutoff", "2025-01-01T00:00:00Z",
        "--instrument-id", str(instrument.id),
    ])

    report = backfill_cli.execute(args)

    assert _counts(session) == before
    assert report["mode"] == "dry_run_plan"
    assert report["request"]["policy"]["observation_cutoff"] == "2025-01-01T00:00:00.000000Z"
    json.dumps(report, ensure_ascii=False)


def test_streaming_plan_and_apply_do_not_require_a_market_wide_plan(session: Session):
    first, dates = _seed(session)
    second = Instrument(
        krx_short_code="EMABF2", name="EMA backfill 2", market="KOSPI",
        security_type="stock", listing_status="listed",
    )
    symbol = Symbol(code="EMABF2", name="EMA backfill 2", market="KOSPI")
    session.add_all((second, symbol))
    session.flush()
    mapping = ProviderSymbol(
        instrument_id=second.id, provider="kiwoom", provider_symbol="EMABF2",
        valid_from=date(2020, 1, 1), mapping_status="matched",
    )
    session.add(mapping)
    session.flush()
    for index, trade_date in enumerate(dates):
        close = Decimal(200 + index)
        observation = PriceObservation(
            symbol_id=symbol.id, trade_date=trade_date, open=close, high=close + 1,
            low=close - 1, close=close, volume=1000, change_rate=Decimal(0),
            provider="kiwoom", parser_version="kiwoom-v2", adjustment_type="1",
            payload_hash=f"{index + 11:064x}", observed_at=datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=index),
        )
        session.add(observation)
        session.flush()
        IndicatorRepository(session).create_identity_snapshot(
            price_observation_id=observation.id, instrument_id=second.id,
            provider_symbol_mapping_id=mapping.id, provider="kiwoom", provider_symbol="EMABF2",
            mapping_status="matched", mapping_valid_from=date(2020, 1, 1),
            mapping_valid_to=None, resolver_version="resolver-v1", resolved_at=observation.observed_at,
        )
    session.commit()
    service = _service(session)
    request = EmaHistoricalBackfillRequest(
        start=dates[0], end=dates[-1], policy=_policy(),
        instrument_ids=(first.id, second.id), chunk_size=1,
    )
    report = service.streaming_plan_report(request)
    application = service.apply_request(request, plan_report_hash=report["report_hash"])

    assert report["counts"]["targets"] == 2
    assert application.created == 2
    assert _counts(session) == (2, 2, 10, 40)

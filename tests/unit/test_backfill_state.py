"""BT06A: a historical backfill run is a frozen, resumable unit of work."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.instrument import Instrument
from app.repositories.historical_backfill_repository import HistoricalBackfillRepository
from app.repositories.price_repository import PriceRepository
from app.services.historical_backfill import HistoricalBackfillPlan, HistoricalBackfillService, HistoricalBackfillTarget


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _plan(*, budget: int = 12) -> HistoricalBackfillPlan:
    return HistoricalBackfillPlan(
        start=date(2020, 1, 2),
        end=date(2020, 1, 3),
        provider="kiwoom",
        adjustment_type="1",
        base_date="20260103",
        request_budget=budget,
        targets=(
            HistoricalBackfillTarget(
                instrument_id=1,
                provider_code="000001",
                symbol_id=7,
                market="KOSPI",
                expected_dates=(date(2020, 1, 2), date(2020, 1, 3)),
            ),
        ),
    )


def test_run_id_freezes_the_plan_and_resumes_by_target_checkpoint():
    session = _session()
    session.add(Instrument(krx_short_code="000001", isin="KR7000000001", name="표본", market="KOSPI", security_type="stock"))
    session.flush()
    repository = HistoricalBackfillRepository(session)

    run, created = repository.create_or_resume("bt06-test", _plan())
    assert created is True
    assert run.manifest_hash
    assert run.status == "running"
    assert len(run.targets) == 1

    checkpoint = repository.mark_target_progress(
        run_id="bt06-test", instrument_id=1, confirmed_dates=[date(2020, 1, 2)]
    )
    assert checkpoint.status == "running"
    assert checkpoint.confirmed_through == date(2020, 1, 2)
    assert checkpoint.remaining_dates == ["2020-01-03"]

    resumed, created = repository.create_or_resume("bt06-test", _plan())
    assert created is False
    assert resumed.id == run.id
    assert resumed.targets[0].confirmed_dates == ["2020-01-02"]


def test_resume_rejects_a_changed_budget_or_target_universe():
    session = _session()
    repository = HistoricalBackfillRepository(session)
    repository.create_or_resume("bt06-frozen", _plan())

    try:
        repository.create_or_resume("bt06-frozen", _plan(budget=13))
    except ValueError as exc:
        assert "frozen" in str(exc)
    else:
        raise AssertionError("a changed plan was allowed to resume")


def test_market_transfer_keeps_independent_checkpoints_for_one_instrument():
    session = _session()
    repository = HistoricalBackfillRepository(session)
    plan = HistoricalBackfillPlan(
        start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom", adjustment_type="1",
        base_date="20260103", request_budget=12,
        targets=(
            HistoricalBackfillTarget(1, "000001", 7, "KOSDAQ", (date(2020, 1, 2),)),
            HistoricalBackfillTarget(1, "000001", 7, "KOSPI", (date(2020, 1, 3),)),
        ),
    )
    run, _ = repository.create_or_resume("market-transfer", plan)
    repository.mark_target_progress(
        run_id="market-transfer", instrument_id=1, market="KOSDAQ", confirmed_dates=[date(2020, 1, 2)]
    )

    states = {state.market: state for state in run.targets}
    assert states["KOSDAQ"].status == "completed"
    assert states["KOSPI"].status == "pending"


def test_dry_run_reports_frozen_target_scope_without_requesting_or_writing_prices():
    session = _session()
    plan = HistoricalBackfillPlan(
        start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom", adjustment_type="1",
        base_date="20260103", request_budget=12, dry_run=True,
        targets=(
            HistoricalBackfillTarget(1, "000001", 7, "KOSPI", (date(2020, 1, 2), date(2020, 1, 3))),
            HistoricalBackfillTarget(2, "", None, "KOSDAQ", (date(2020, 1, 2),)),
        ),
    )
    report = HistoricalBackfillService(
        session, HistoricalBackfillRepository(session), PriceRepository(session)
    ).execute("dry-scope", plan, lambda _target, _budget: [])

    assert report.target_count == 2
    assert report.expected_rows == 3
    assert report.unresolved_targets == 1

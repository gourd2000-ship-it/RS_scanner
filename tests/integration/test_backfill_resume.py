"""BT06B: page commits can be replayed without canonical price duplication."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.crawler.sources.kiwoom_history import KiwoomHistoryPage
from app.models.daily_price import DailyPrice
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.historical_backfill_repository import HistoricalBackfillRepository
from app.repositories.price_repository import PriceRepository
from app.services.historical_backfill import HistoricalBackfillPlan, HistoricalBackfillService, HistoricalBackfillTarget
from app.schemas.market_data import DailyPricePayload


def _row(day: str, close: str = "100") -> DailyPricePayload:
    value = Decimal(close)
    return DailyPricePayload(
        trade_date=date.fromisoformat(day), open=value, high=value + 1, low=value - 1,
        close=value, volume=100, change_rate=Decimal("0"),
    )


def _page(number: int, *rows: DailyPricePayload, payload_hash: str) -> KiwoomHistoryPage:
    return KiwoomHistoryPage(
        page_number=number, rows=tuple(rows), received_row_count=len(rows), invalid_row_count=0,
        response_bytes=10, retry_count=0, duplicate_date_count=0, source_payload_hash=payload_hash,
    )


class _MeasuredPages(list):
    def __init__(
        self,
        *pages: KiwoomHistoryPage,
        request_count: int,
        terminal_reason: str | None = None,
    ) -> None:
        super().__init__(pages)
        self.summary = SimpleNamespace(request_count=request_count, terminal_reason=terminal_reason)


def test_resume_replays_a_page_without_duplicate_canonical_rows_and_keeps_lineage():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="000001", isin="KR7000000001", name="표본", market="KOSPI",
            security_type="stock", listing_status="listed",
        )
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000001", name="표본", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom",
            adjustment_type="1", base_date="20260103", request_budget=5,
            targets=(HistoricalBackfillTarget(
                instrument_id=instrument.id, provider_code="000001", symbol_id=symbol.id,
                market="KOSPI", expected_dates=(date(2020, 1, 2), date(2020, 1, 3)),
            ),),
        )
        service = HistoricalBackfillService(
            session, HistoricalBackfillRepository(session), PriceRepository(session)
        )

        first = service.execute("resume-case", plan, lambda _target, _budget: [_page(1, _row("2020-01-02"), payload_hash="a" * 64)])
        assert first.inserted == 1
        assert first.completed_targets == 0

        second = service.execute("resume-case", plan, lambda _target, _budget: [
            _page(1, _row("2020-01-02"), _row("2020-01-03"), payload_hash="b" * 64)
        ])
        assert (second.inserted, second.unchanged, second.conflict, second.failed) == (1, 1, 0, 0)
        assert second.completed_targets == 1
        assert session.scalar(select(func.count()).select_from(DailyPrice)) == 2
        state = HistoricalBackfillRepository(session).get_run("resume-case").targets[0]
        assert state.status == "completed"
        assert state.confirmed_dates == ["2020-01-02", "2020-01-03"]
        observations = list(session.scalars(select(app.models.PriceObservation).order_by(app.models.PriceObservation.id)))
        assert observations[-1].historical_backfill_run_id is not None
        assert observations[-1].adjustment_type == "1"
        assert observations[-1].payload_hash == "b" * 64


def test_successful_collection_completes_target_while_preserving_unobserved_dates_for_gap_validation():
    """A provider can finish its history without supplying every expected trade date.

    The target has still been collected and must not be fetched repeatedly; its
    retained remaining dates are the input to BT07 gap classification.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="000008", isin="KR7000000008", name="결측", market="KOSPI",
            security_type="stock", listing_status="listed",
        )
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000008", name="결측", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom",
            adjustment_type="1", base_date="20260103", request_budget=1,
            targets=(HistoricalBackfillTarget(
                instrument.id, "000008", symbol.id, "KOSPI",
                (date(2020, 1, 2), date(2020, 1, 3)),
            ),),
        )
        service = HistoricalBackfillService(
            session, HistoricalBackfillRepository(session), PriceRepository(session)
        )

        result = service.execute(
            "complete-with-gap", plan,
            lambda _target, _budget: _MeasuredPages(
                _page(1, _row("2020-01-02"), payload_hash="e" * 64),
                request_count=1,
                terminal_reason="collection_start_reached",
            ),
        )

        state = HistoricalBackfillRepository(session).get_run("complete-with-gap").targets[0]
        assert result.completed_targets == 1
        assert state.status == "completed"
        assert state.confirmed_dates == ["2020-01-02"]
        assert state.remaining_dates == ["2020-01-03"]


def test_reconciliation_completes_an_existing_target_that_reached_its_expected_start():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="000009", isin="KR7000000009", name="기존수집", market="KOSPI",
            security_type="stock", listing_status="listed",
        )
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000009", name="기존수집", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom",
            adjustment_type="1", base_date="20260103", request_budget=1,
            targets=(HistoricalBackfillTarget(
                instrument.id, "000009", symbol.id, "KOSPI",
                (date(2020, 1, 2), date(2020, 1, 3)),
            ),),
        )
        service = HistoricalBackfillService(
            session, HistoricalBackfillRepository(session), PriceRepository(session)
        )
        service.execute(
            "reconcile-covered-start", plan,
            lambda _target, _budget: _MeasuredPages(
                _page(1, _row("2020-01-02"), payload_hash="f" * 64), request_count=1,
            ),
        )

        reconciled = service.reconcile_targets_with_confirmed_start("reconcile-covered-start")

        run = HistoricalBackfillRepository(session).get_run("reconcile-covered-start")
        assert reconciled == 1
        assert run.status == "completed"
        assert run.targets[0].status == "completed"
        assert run.targets[0].remaining_dates == ["2020-01-03"]


def test_conflicting_price_is_recorded_as_a_candidate_and_not_overwritten():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000002", isin="KR7000000002", name="충돌", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000002", name="충돌", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 2), provider="kiwoom", adjustment_type="1",
            base_date="20260103", request_budget=5,
            targets=(HistoricalBackfillTarget(instrument.id, "000002", symbol.id, "KOSPI", (date(2020, 1, 2),)),),
        )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        service.execute("conflict-one", plan, lambda _target, _budget: [_page(1, _row("2020-01-02", "100"), payload_hash="c" * 64)])
        result = service.execute("conflict-two", plan, lambda _target, _budget: [_page(1, _row("2020-01-02", "200"), payload_hash="d" * 64)])

        assert result.conflict == 1
        assert session.scalar(select(DailyPrice.close)) == Decimal("100")
        candidate = session.scalars(select(app.models.PriceObservation).order_by(app.models.PriceObservation.id.desc())).first()
        assert candidate.observation_metadata["canonical_disposition"] == "conflict_candidate"


def test_request_budget_is_global_to_a_run_and_leaves_later_targets_pending():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000003", isin="KR7000000003", name="예산", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000003", name="예산", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 2), provider="kiwoom", adjustment_type="1",
            base_date="20260103", request_budget=2,
            targets=(
                HistoricalBackfillTarget(instrument.id, "000003", symbol.id, "KOSPI", (date(2020, 1, 2),)),
                HistoricalBackfillTarget(instrument.id + 1, "000004", symbol.id, "KOSDAQ", (date(2020, 1, 2),)),
            ),
        )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        requested_budgets = []

        def pages(_target, budget):
            requested_budgets.append(budget)
            return _MeasuredPages(_page(1, _row("2020-01-02"), payload_hash="f" * 64), request_count=2)

        report = service.execute("global-budget", plan, pages)

        assert requested_budgets == [2]
        assert report.requests_used == 2
        assert report.budget_exhausted_targets == 1
        states = HistoricalBackfillRepository(session).get_run("global-budget").targets
        assert [state.status for state in states] == ["completed", "pending"]


def test_resume_uses_only_the_unspent_global_request_budget():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000004", isin="KR7000000004", name="재개 예산", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000004", name="재개 예산", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom", adjustment_type="1",
            base_date="20260103", request_budget=3,
            targets=(HistoricalBackfillTarget(instrument.id, "000004", symbol.id, "KOSPI", (date(2020, 1, 2), date(2020, 1, 3))),),
        )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        requested_budgets = []

        def first_pages(_target, budget):
            requested_budgets.append(budget)
            return _MeasuredPages(_page(1, _row("2020-01-02"), payload_hash="a" * 64), request_count=2)

        def resumed_pages(_target, budget):
            requested_budgets.append(budget)
            return _MeasuredPages(_page(1, _row("2020-01-03"), payload_hash="b" * 64), request_count=1)

        service.execute("resume-global-budget", plan, first_pages)
        report = service.execute("resume-global-budget", plan, resumed_pages)

        assert requested_budgets == [3, 1]
        assert report.requests_used == 3


def test_resume_can_extend_an_exhausted_approved_run_without_replacing_its_manifest():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000005", isin="KR7000000005", name="연장", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000005", name="연장", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 3), provider="kiwoom", adjustment_type="1",
            base_date="20260103", request_budget=1,
            targets=(HistoricalBackfillTarget(instrument.id, "000005", symbol.id, "KOSPI", (date(2020, 1, 2), date(2020, 1, 3))),),
        )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        service.execute("extend-budget", plan, lambda _target, _budget: _MeasuredPages(
            _page(1, _row("2020-01-02"), payload_hash="a" * 64), request_count=1,
        ))

        report = service.execute(
            "extend-budget", plan,
            lambda _target, _budget: _MeasuredPages(_page(1, _row("2020-01-03"), payload_hash="b" * 64), request_count=1),
            additional_request_budget=1,
        )

        run = HistoricalBackfillRepository(session).get_run("extend-budget")
        assert (run.request_budget, run.requests_used, run.manifest_hash) == (2, 2, plan.manifest_hash)
        assert report.completed_targets == 1


def test_pending_only_resume_skips_existing_partial_target_and_advances_pending_target():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = Instrument(krx_short_code="000006", isin="KR7000000006", name="부분", market="KOSPI", security_type="stock", listing_status="listed")
        second = Instrument(krx_short_code="000007", isin="KR7000000007", name="다음", market="KOSPI", security_type="stock", listing_status="listed")
        session.add_all([first, second])
        session.flush()
        first_symbol = Symbol(code="000006", name="부분", market="KOSPI", instrument_id=first.id)
        second_symbol = Symbol(code="000007", name="다음", market="KOSPI", instrument_id=second.id)
        session.add_all([first_symbol, second_symbol])
        session.flush()
        plan = HistoricalBackfillPlan(
            start=date(2020, 1, 2), end=date(2020, 1, 2), provider="kiwoom", adjustment_type="1",
            base_date="20260103", request_budget=1,
            targets=(
                HistoricalBackfillTarget(first.id, "000006", first_symbol.id, "KOSPI", (date(2020, 1, 2),)),
                HistoricalBackfillTarget(second.id, "000007", second_symbol.id, "KOSPI", (date(2020, 1, 2),)),
            ),
        )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        service.execute("pending-only", plan, lambda _target, _budget: _MeasuredPages(
            _page(1, _row("2020-01-02"), payload_hash="a" * 64), request_count=1,
        ))
        run = HistoricalBackfillRepository(session).get_run("pending-only")
        run.targets[0].status = "running"
        run.targets[0].remaining_dates = ["2020-01-02"]
        session.commit()

        requested = []
        service.execute(
            "pending-only", plan,
            lambda target, _budget: (requested.append(target.instrument_id) or _MeasuredPages(
                _page(1, _row("2020-01-02"), payload_hash="b" * 64), request_count=1,
            )),
            additional_request_budget=1,
            process_statuses=("pending",),
        )

        assert requested == [second.id]

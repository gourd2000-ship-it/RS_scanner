from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.base import Base
import app.models  # noqa: F401
from app.crawler.parsers.krx import KrxStockMembership
from app.crawler.sources.krx import KrxUniverseFetchResult
from app.repositories.krx_universe_repository import KrxUniverseRepository
from app.services.batch.context import BatchContext
from app.services.batch.sync_krx_universe import sync_krx_universe


class FakeKrxSource:
    def __init__(self, result: KrxUniverseFetchResult) -> None:
        self.result = result
        self.requested_dates: list[date] = []
        self.latest_requested_dates: list[date] = []

    def fetch_stock_membership(self, as_of_date: date) -> KrxUniverseFetchResult:
        self.requested_dates.append(as_of_date)
        return self.result

    def fetch_latest_stock_membership(self, as_of_date: date) -> KrxUniverseFetchResult:
        self.latest_requested_dates.append(as_of_date)
        return self.result


def build_context(*, target_date: date) -> tuple[BatchContext, KrxUniverseRepository]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = KrxUniverseRepository(sessionmaker(bind=engine)())
    return (
        BatchContext(
            symbol_repository=object(),
            benchmark_repository=object(),
            price_repository=object(),
            rs_repository=object(),
            krx_universe_repository=repository,
            target_date=target_date,
            job_id=17,
            universe_snapshot_status="completed",
        ),
        repository,
    )


def make_member(*, code: str, market: str) -> KrxStockMembership:
    return KrxStockMembership(
        as_of_date=date(2026, 8, 19),
        code=code,
        name="테스트 종목",
        market=market,
        security_type="stock",
        listing_status="listed_observed",
        trading_status="unknown",
        raw_fields={"BAS_DD": "20260819", "ISU_CD": code},
    )


def test_completed_shadow_fetch_persists_a_job_linked_snapshot_without_changing_naver_state():
    context, repository = build_context(target_date=date(2026, 8, 19))
    source = FakeKrxSource(
        KrxUniverseFetchResult(
            as_of_date=date(2026, 8, 19),
            members=[
                make_member(code="005930", market="KOSPI"),
                make_member(code="247540", market="KOSDAQ"),
            ],
            complete=True,
        )
    )

    result = sync_krx_universe(context, source)

    assert result.status == "completed"
    assert result.member_count == 2
    assert source.latest_requested_dates == [date(2026, 8, 19)]
    assert context.krx_universe_snapshot_status == "completed"
    assert context.universe_snapshot_status == "completed"

    snapshot = repository.get(result.snapshot_id)
    assert snapshot is not None
    assert snapshot.crawl_job_id == 17
    assert snapshot.status == "completed"
    assert [(row.code, row.market) for row in repository.list_memberships(snapshot.id)] == [
        ("005930", "KOSPI"),
        ("247540", "KOSDAQ"),
    ]


def test_partial_shadow_fetch_is_recorded_without_mutating_the_naver_snapshot_status():
    context, repository = build_context(target_date=date(2026, 8, 19))
    source = FakeKrxSource(
        KrxUniverseFetchResult(
            as_of_date=date(2026, 8, 19),
            members=[make_member(code="005930", market="KOSPI")],
            complete=False,
            error_message="KOSDAQ:KrxUniverseParseError",
        )
    )

    result = sync_krx_universe(context, source)

    assert result.status == "partial"
    assert context.krx_universe_snapshot_status == "partial"
    assert context.universe_snapshot_status == "completed"
    assert repository.get_latest_completed(scope="stock_membership") is None

    snapshot = repository.get(result.snapshot_id)
    assert snapshot is not None
    assert snapshot.status == "partial"
    assert snapshot.error_message == "KOSDAQ:KrxUniverseParseError"
    assert len(repository.list_memberships(snapshot.id)) == 1


def test_shadow_snapshot_uses_the_actual_krx_publication_date_when_it_lags_the_batch():
    context, repository = build_context(target_date=date(2026, 8, 20))
    source = FakeKrxSource(
        KrxUniverseFetchResult(
            as_of_date=date(2026, 8, 19),
            members=[
                make_member(code="005930", market="KOSPI"),
                make_member(code="247540", market="KOSDAQ"),
            ],
            complete=True,
        )
    )

    result = sync_krx_universe(context, source)

    snapshot = repository.get(result.snapshot_id)
    assert source.latest_requested_dates == [date(2026, 8, 20)]
    assert snapshot is not None
    assert snapshot.as_of_date == date(2026, 8, 19)
    assert snapshot.source_metadata["requested_as_of_date"] == "2026-08-20"

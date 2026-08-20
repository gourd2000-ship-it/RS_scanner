from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.base import Base
import app.models  # noqa: F401
from app.repositories.krx_universe_repository import (
    KrxMembershipInput,
    KrxUniverseRepository,
)


def build_repository() -> KrxUniverseRepository:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return KrxUniverseRepository(sessionmaker(bind=engine)())


def test_completed_krx_snapshot_preserves_membership_without_mutating_symbols():
    repository = build_repository()
    snapshot = repository.create_snapshot(
        crawl_job_id=None,
        source="krx_open_api",
        as_of_date=date(2026, 8, 19),
        scope="stock_membership",
    )

    repository.add_memberships(
        snapshot.id,
        [
            KrxMembershipInput(
                code="005930",
                isin="KR7005930003",
                name="삼성전자",
                market="KOSPI",
                security_type="stock",
            ),
            KrxMembershipInput(
                code="247540",
                isin=None,
                name="에코프로비엠",
                market="KOSDAQ",
                security_type="stock",
            ),
        ],
    )
    repository.complete_snapshot(
        snapshot.id,
        status="completed",
        members_seen=2,
        members_valid=2,
        snapshot_hash="a" * 64,
    )

    latest = repository.get_latest_completed(scope="stock_membership")
    assert latest is not None
    assert latest.id == snapshot.id
    assert latest.as_of_date == date(2026, 8, 19)
    assert latest.status == "completed"

    members = repository.list_memberships(snapshot.id)
    assert [(member.code, member.market) for member in members] == [
        ("005930", "KOSPI"),
        ("247540", "KOSDAQ"),
    ]
    assert all(member.listing_status == "listed_observed" for member in members)
    assert all(member.trading_status == "unknown" for member in members)


def test_partial_krx_snapshot_is_not_selected_as_latest_completed():
    repository = build_repository()
    completed = repository.create_snapshot(
        crawl_job_id=None,
        source="krx_open_api",
        as_of_date=date(2026, 8, 18),
        scope="stock_membership",
    )
    repository.complete_snapshot(
        completed.id,
        status="completed",
        members_seen=1,
        members_valid=1,
    )

    partial = repository.create_snapshot(
        crawl_job_id=None,
        source="krx_open_api",
        as_of_date=date(2026, 8, 19),
        scope="stock_membership",
    )
    repository.complete_snapshot(
        partial.id,
        status="partial",
        members_seen=1,
        members_valid=0,
        error_message="KOSDAQ 응답 누락",
    )

    latest = repository.get_latest_completed(scope="stock_membership")
    assert latest is not None
    assert latest.id == completed.id
    assert repository.list_memberships(partial.id) == []

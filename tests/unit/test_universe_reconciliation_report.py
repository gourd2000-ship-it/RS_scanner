from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.base import Base
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.krx_universe_repository import KrxMembershipInput, KrxUniverseRepository
from app.services.monitoring.universe_reconciliation import build_universe_reconciliation_report
from app.services.monitoring.universe_reconciliation import UniverseReconciliationReport
from scripts.report_universe_reconciliation import write_reconciliation_report


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def add_krx_snapshot(session: Session, *, status: str = "completed") -> int:
    repository = KrxUniverseRepository(session)
    snapshot = repository.create_snapshot(
        crawl_job_id=None,
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 19),
    )
    if status == "completed":
        repository.add_memberships(
            snapshot.id,
            [
                KrxMembershipInput(code="005930", isin=None, name="삼성전자", market="KOSPI", security_type="stock"),
                KrxMembershipInput(code="111111", isin=None, name="시장충돌", market="KOSDAQ", security_type="stock"),
                KrxMembershipInput(code="222222", isin=None, name="KRX만", market="KOSDAQ", security_type="stock"),
            ],
        )
    repository.complete_snapshot(
        snapshot.id,
        status=status,
        members_seen=3 if status == "completed" else 0,
        members_valid=3 if status == "completed" else 0,
        error_message="KOSDAQ:Timeout" if status != "completed" else None,
    )
    return snapshot.id


def test_report_compares_latest_completed_snapshots_without_mutating_symbols():
    session = make_session()
    krx_snapshot_id = add_krx_snapshot(session)
    naver_snapshot = SymbolUniverseSnapshot(
        provider="naver",
        status="completed",
        started_at=datetime(2026, 8, 19, 18, 0),
        finished_at=datetime(2026, 8, 19, 18, 1),
    )
    session.add(naver_snapshot)
    session.flush()
    session.add_all(
        [
            Symbol(code="005930", name="삼성전자", market="KOSPI", last_snapshot_id=naver_snapshot.id),
            Symbol(code="111111", name="시장충돌", market="KOSPI", last_snapshot_id=naver_snapshot.id),
            Symbol(code="333333", name="Naver만", market="KOSPI", last_snapshot_id=naver_snapshot.id),
            Symbol(code="0005", name="잘린 레거시", market="KOSPI", last_snapshot_id=naver_snapshot.id),
            Symbol(
                code="ETF001", name="범위 밖 ETF", market="KOSPI", symbol_type="etf", last_snapshot_id=naver_snapshot.id
            ),
        ]
    )
    session.commit()

    report = build_universe_reconciliation_report(session, sample_limit=10)

    assert report.krx_snapshot_id == krx_snapshot_id
    assert report.naver_snapshot_id == naver_snapshot.id
    assert report.counts == {
        "krx_total": 3,
        "naver_total": 5,
        "exact": 1,
        "ambiguous": 1,
        "unmatched_krx": 1,
        "unmatched_naver": 1,
        "out_of_scope_naver": 1,
        "legacy_candidate": 0,
        "invalid_legacy": 1,
    }
    assert report.mapping_rate == 1 / 3
    assert report.samples["unmatched_krx"] == ["222222"]
    assert report.samples["ambiguous"] == ["111111"]
    assert report.samples["invalid_legacy"] == ["0005"]
    assert report.samples["unmatched_naver"] == ["333333"]
    assert report.samples["out_of_scope_naver"] == ["ETF001"]
    assert {symbol.code for symbol in session.query(Symbol).all()} == {
        "005930",
        "111111",
        "333333",
        "0005",
        "ETF001",
    }


def test_report_surfaces_latest_partial_krx_snapshot_as_an_observation_alert():
    session = make_session()
    add_krx_snapshot(session)
    partial_snapshot_id = add_krx_snapshot(session, status="partial")
    session.add(
        SymbolUniverseSnapshot(
            provider="naver",
            status="completed",
            started_at=datetime.utcnow() - timedelta(minutes=1),
            finished_at=datetime.utcnow(),
        )
    )
    session.commit()

    report = build_universe_reconciliation_report(session)

    assert report.krx_snapshot_id is not None
    assert report.latest_krx_snapshot_id == partial_snapshot_id
    assert report.latest_krx_status == "partial"
    assert report.alerts == ["krx_snapshot_not_completed"]


def test_reconciliation_cli_writer_emits_a_read_only_json_report(tmp_path):
    report = UniverseReconciliationReport(
        krx_snapshot_id=7,
        naver_snapshot_id=8,
        latest_krx_snapshot_id=7,
        latest_krx_status="completed",
        counts={"krx_total": 1, "naver_total": 1, "exact": 1, "ambiguous": 0, "unmatched_krx": 0, "legacy_candidate": 0, "invalid_legacy": 0},
        mapping_rate=1.0,
        samples={"ambiguous": [], "unmatched_krx": [], "legacy_candidate": [], "invalid_legacy": []},
        alerts=[],
    )

    output = write_reconciliation_report(report, output_dir=tmp_path, report_stem="krx_diff")

    assert output.name == "krx_diff.json"
    assert '"krx_snapshot_id": 7' in output.read_text(encoding="utf-8")

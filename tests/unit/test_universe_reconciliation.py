from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.krx_universe import KrxUniverseSnapshot
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.universe_reconciliation_repository import UniverseReconciliationRepository
from app.services.universe_reconciliation import (
    KRXMemberCandidate,
    NaverSymbolCandidate,
    reconcile_universe_candidates,
    run_universe_reconciliation,
)


def test_reconciliation_uses_exact_code_then_isin_and_never_auto_matches_name_only():
    result = reconcile_universe_candidates(
        krx_members=[
            KRXMemberCandidate("005930", "KR7005930003", "삼성전자", "KOSPI", "stock"),
            KRXMemberCandidate("111111", "KR7111111001", "ISIN 우선", "KOSDAQ", "stock"),
            KRXMemberCandidate("0005A0", None, "레거시 ETF", "KOSPI", "etf"),
            KRXMemberCandidate("222222", None, "이름만 일치", "KOSDAQ", "stock"),
        ],
        naver_symbols=[
            NaverSymbolCandidate("005930", None, "삼성전자", "KOSPI", "stock"),
            NaverSymbolCandidate("NAV111", "KR7111111001", "다른 이름", "KOSDAQ", "stock"),
            NaverSymbolCandidate("0005", None, "레거시 ETF", "KOSPI", "etf"),
            NaverSymbolCandidate("333333", None, "이름만 일치", "KOSDAQ", "stock"),
            NaverSymbolCandidate("BAD", None, "잘린 코드", "KOSPI", "stock"),
        ],
    )

    by_krx = {row.krx_code: row for row in result.krx_results}
    assert by_krx["005930"].status == "matched"
    assert by_krx["005930"].match_method == "exact_code"
    assert by_krx["111111"].status == "matched"
    assert by_krx["111111"].match_method == "isin"
    assert by_krx["0005A0"].status == "unmatched"
    assert by_krx["222222"].status == "ambiguous"
    assert by_krx["222222"].candidate_codes == ("333333",)
    assert result.naver_results["0005"].status == "legacy_candidate"
    assert result.naver_results["BAD"].status == "invalid_legacy"


def test_reconciliation_run_is_idempotent_for_the_same_snapshot_pair():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    krx_snapshot = KrxUniverseSnapshot(
        source="krx_open_api",
        scope="stock_membership",
        as_of_date=date(2026, 8, 19),
        status="completed",
    )
    naver_snapshot = SymbolUniverseSnapshot(provider="naver", status="completed")
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    repository = UniverseReconciliationRepository(session)

    first = repository.get_or_create_run(
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        report={"mapping_rate": 1.0},
    )
    second = repository.get_or_create_run(
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        report={"mapping_rate": 0.5},
    )

    assert second.id == first.id
    assert second.report == {"mapping_rate": 1.0}


def test_database_reconciliation_persists_an_approval_ready_run_without_mapping_mutation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    krx_snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    naver_snapshot = SymbolUniverseSnapshot(provider="naver", status="completed")
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    from app.models.krx_universe import KrxUniverseMembership
    from app.models.symbol import Symbol

    session.add_all(
        [
            KrxUniverseMembership(
                snapshot_id=krx_snapshot.id, code="005930", name="삼성전자", market="KOSPI",
                security_type="stock", listing_status="listed_observed", trading_status="unknown", raw_fields={},
            ),
            Symbol(
                code="005930", name="삼성전자", market="KOSPI", symbol_type="stock",
                last_snapshot_id=naver_snapshot.id,
            ),
        ]
    )
    session.commit()

    run = run_universe_reconciliation(
        session, krx_snapshot_id=krx_snapshot.id, naver_snapshot_id=naver_snapshot.id
    )

    assert run.status == "pending_review"
    assert run.report["counts"]["exact"] == 1
    assert run.report["mapping_rate"] == 1.0


def test_operator_approval_records_reviewer_and_timestamp_without_rewriting_report():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    krx_snapshot = KrxUniverseSnapshot(
        source="krx_open_api", scope="stock_membership", as_of_date=date(2026, 8, 19), status="completed"
    )
    naver_snapshot = SymbolUniverseSnapshot(provider="naver", status="completed")
    session.add_all([krx_snapshot, naver_snapshot])
    session.flush()
    repository = UniverseReconciliationRepository(session)
    run = repository.get_or_create_run(
        krx_snapshot_id=krx_snapshot.id,
        naver_snapshot_id=naver_snapshot.id,
        report={"mapping_rate": 1.0, "counts": {"exact": 1}},
    )

    approved = repository.approve_run(run.id, approved_by="ops-reviewer")

    assert approved.status == "approved"
    assert approved.decision == "approved"
    assert approved.approved_by == "ops-reviewer"
    assert approved.decided_at is not None
    assert approved.report == {"mapping_rate": 1.0, "counts": {"exact": 1}}

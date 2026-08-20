import csv
import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.base import Base
import app.models  # noqa: F401
from app.models.symbol import Symbol
from app.models.symbol_universe_snapshot import SymbolUniverseSnapshot
from app.repositories.universe_audit_repository import UniverseAuditRepository
from app.services.universe_audit import AuditSymbol, build_universe_audit_report
import scripts.audit_universe as audit_cli
from scripts.audit_universe import persist_audit_run, write_audit_reports


def test_audit_cli_writes_json_and_csv_reports(tmp_path):
    report = build_universe_audit_report(
        symbols=[
            AuditSymbol(
                code="0005A0",
                name="정상 ETF",
                market="KOSPI",
                symbol_type="etf",
                is_active=True,
                last_snapshot_id=10,
            ),
            AuditSymbol(
                code="0005",
                name="정상 ETF",
                market="KOSPI",
                symbol_type="etf",
                is_active=True,
                last_snapshot_id=8,
            ),
        ],
        latest_completed_snapshot_id=10,
    )

    json_path, csv_path = write_audit_reports(
        report,
        output_dir=tmp_path,
        report_stem="universe_audit_test",
        generated_at=datetime(2026, 8, 20, 0, 30, tzinfo=UTC),
    )

    report_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert report_json["candidate_count"] == 1
    assert report_json["generated_at"] == "2026-08-20T00:30:00Z"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "code": "0005",
            "name": "정상 ETF",
            "market": "KOSPI",
            "symbol_type": "etf",
            "last_snapshot_id": "8",
            "reason_codes": "invalid_legacy,prefix_collision,missing_from_latest_snapshot,stale_active",
            "replacement_code": "0005A0",
            "prefix_matches": "0005A0",
        }
    ]


def test_audit_cli_persists_run_only_when_explicitly_requested():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = SymbolUniverseSnapshot(provider="naver", status="completed")
        symbol = Symbol(
            code="0005",
            name="정상 ETF",
            market="KOSPI",
            symbol_type="etf",
            is_active=True,
        )
        session.add_all([snapshot, symbol])
        session.flush()
        report = build_universe_audit_report(
            symbols=[
                AuditSymbol(
                    code="0005",
                    name="정상 ETF",
                    market="KOSPI",
                    symbol_type="etf",
                    is_active=True,
                    last_snapshot_id=None,
                )
            ],
            latest_completed_snapshot_id=snapshot.id,
        )

        run = persist_audit_run(
            session,
            snapshot_id=snapshot.id,
            report=report,
            requested_by="operator",
        )

        assert run.requested_by == "operator"
        assert UniverseAuditRepository(session).list_decisions(run.id)[0].status == "pending"
    engine.dispose()


def test_audit_cli_reads_legacy_symbols_schema_before_audit_migration(monkeypatch):
    """Dry-run은 새 audit 컬럼이 아직 없는 DB에서도 읽기만 해야 한다."""
    engine = create_engine("sqlite://")
    SymbolUniverseSnapshot.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            SymbolUniverseSnapshot(
                id=10,
                market="ALL",
                provider="naver",
                status="completed",
            )
        )
        session.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE symbols (
                    id INTEGER PRIMARY KEY,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    market VARCHAR(20) NOT NULL,
                    symbol_type VARCHAR(20) NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    last_snapshot_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO symbols
                    (id, code, name, market, symbol_type, is_active, last_snapshot_id)
                VALUES (1, '0005', '잘린 ETF', 'KOSPI', 'etf', 1, 8)
                """
            )
        )

    monkeypatch.setattr(audit_cli, "SessionLocal", sessionmaker(bind=engine))

    report = audit_cli.build_report_from_database(snapshot_id=10)

    assert [candidate.code for candidate in report.candidates] == ["0005"]
    assert report.latest_completed_snapshot_id == 10
    engine.dispose()

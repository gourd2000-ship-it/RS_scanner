from app.services.universe_audit import AuditSymbol, build_universe_audit_report


def test_universe_audit_reports_invalid_prefix_and_stale_active_candidates():
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
            AuditSymbol(
                code="005930",
                name="삼성전자",
                market="KOSPI",
                symbol_type="stock",
                is_active=True,
                last_snapshot_id=None,
            ),
            AuditSymbol(
                code="00088K",
                name="한화3우B",
                market="KOSPI",
                symbol_type="stock",
                is_active=False,
                last_snapshot_id=10,
            ),
        ],
        latest_completed_snapshot_id=10,
    )

    candidates_by_code = {
        candidate.code: candidate for candidate in report.candidates
    }

    truncated = candidates_by_code["0005"]
    assert set(truncated.reason_codes) == {
        "invalid_legacy",
        "prefix_collision",
        "missing_from_latest_snapshot",
        "stale_active",
    }
    assert truncated.replacement_code == "0005A0"
    assert truncated.last_snapshot_id == 8

    stale = candidates_by_code["005930"]
    assert set(stale.reason_codes) == {
        "missing_from_latest_snapshot",
        "stale_active",
    }
    assert stale.replacement_code is None

    assert "0005A0" not in candidates_by_code
    assert "00088K" not in candidates_by_code
    assert report.reason_counts == {
        "invalid_legacy": 1,
        "prefix_collision": 1,
        "missing_from_latest_snapshot": 2,
        "stale_active": 2,
    }


def test_universe_audit_requires_completed_snapshot_for_stale_detection():
    report = build_universe_audit_report(
        symbols=[
            AuditSymbol(
                code="0005",
                name="잘린 ETF",
                market="KOSPI",
                symbol_type="etf",
                is_active=True,
                last_snapshot_id=8,
            )
        ],
        latest_completed_snapshot_id=None,
    )

    candidate = report.candidates[0]
    assert candidate.reason_codes == ("invalid_legacy",)
    assert report.reason_counts == {"invalid_legacy": 1}

from datetime import UTC, date, datetime
from types import SimpleNamespace

from scripts.run_daily_pipeline import latest_completed_trade_date, pipeline_failed


def test_latest_completed_session_handles_holiday_and_preclose():
    settings = SimpleNamespace(market_closed_dates='')
    assert latest_completed_trade_date(settings, datetime(2026, 10, 9, 10, tzinfo=UTC)) == date(2026, 10, 8)
    assert latest_completed_trade_date(settings, datetime(2026, 10, 8, 2, tzinfo=UTC)) == date(2026, 10, 7)
    assert latest_completed_trade_date(settings, datetime(2026, 10, 8, 7, 30, tzinfo=UTC)) == date(2026, 10, 8)


def test_pipeline_reports_blocked_report_only_validation_as_failure():
    batch = {'validation': {'validation_status': 'blocked'}, 'validation_blocked': False}
    assert pipeline_failed({'failed': 0}, batch)


def test_pipeline_reports_source_failure_and_skipped_indicator():
    good = {'validation': {'validation_status': 'passed'}, 'ema': {'outcome': 'completed'}}
    assert pipeline_failed({'failed': 1}, good)
    assert pipeline_failed({'failed': 0}, {**good, 'atr14': {'outcome': 'skipped'}})
    assert not pipeline_failed({'failed': 0}, good)

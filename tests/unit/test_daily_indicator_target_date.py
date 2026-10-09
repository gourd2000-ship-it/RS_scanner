"""A daily indicator cannot complete from prior dates alone."""

from contextlib import nullcontext
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.batch.atr_adapter import calculate_daily_atr14
from app.services.batch.context import build_memory_batch_context
from app.services.batch.volume_adapter import calculate_daily_volume_sma50


TARGET_DATE = date(2025, 9, 17)


def _context_with_read_savepoint():
    context = build_memory_batch_context()
    context.session = SimpleNamespace(begin_nested=nullcontext)
    return context


def _unexpected_call(*_args, **_kwargs):
    pytest.fail("missing target-date evidence must skip before identity selection or calculation")


def test_volume_skips_when_expected_dates_only_contain_prior_observations(monkeypatch):
    context = _context_with_read_savepoint()
    settings = Settings(
        _env_file=None,
        volume_sma50_enabled=True,
        volume_sma50_source_provider="kiwoom",
        volume_sma50_adjustment_type="1",
        volume_sma50_allowed_parser_versions="kiwoom-v2",
    )
    monkeypatch.setattr(
        "app.services.batch.volume_adapter.expected_trade_dates",
        lambda *_args, **_kwargs: (TARGET_DATE - timedelta(days=1),),
    )
    monkeypatch.setattr("app.services.batch.volume_adapter.eligible_instrument_ids", _unexpected_call)
    monkeypatch.setattr("app.services.batch.volume_adapter.VolumeSmaCalculationService", _unexpected_call)

    outcome = calculate_daily_volume_sma50(context, target_date=TARGET_DATE, settings=settings)

    assert outcome.outcome == "skipped"
    assert outcome.reason == "target_date_observations_missing"
    assert outcome.processed == 0 and outcome.failed == 1


def test_atr_skips_when_expected_dates_only_contain_prior_observations(monkeypatch):
    context = _context_with_read_savepoint()
    settings = Settings(
        _env_file=None,
        atr14_enabled=True,
        atr14_source_provider="kiwoom",
        atr14_adjustment_type="1",
        atr14_allowed_parser_versions="kiwoom-v2",
    )
    monkeypatch.setattr(
        "app.services.batch.atr_adapter.expected_trade_dates",
        lambda *_args, **_kwargs: (TARGET_DATE - timedelta(days=1),),
    )
    monkeypatch.setattr("app.services.batch.atr_adapter.eligible_instrument_ids", _unexpected_call)
    monkeypatch.setattr("app.services.batch.atr_adapter.AtrCalculationService", _unexpected_call)

    outcome = calculate_daily_atr14(context, target_date=TARGET_DATE, settings=settings)

    assert outcome.outcome == "skipped"
    assert outcome.reason == "target_date_observations_missing"
    assert outcome.processed == 0 and outcome.failed == 1

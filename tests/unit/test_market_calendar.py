from datetime import date, datetime, timezone
from contextlib import contextmanager
from types import SimpleNamespace

from app.core.market_calendar import batch_target_date, krx_market_day_status
from app.services.batch.orchestrator import BatchOrchestrator
from app.services.batch.context import build_memory_batch_context
from app.services.batch.run_daily_job import run_daily_job


def test_krx_closes_on_substitute_public_holiday():
    status = krx_market_day_status(date(2026, 8, 17))

    assert status.is_open is False
    assert "holiday" in status.reason.lower()


def test_krx_closes_on_labour_day_even_when_it_is_a_weekday():
    status = krx_market_day_status(date(2026, 5, 1))

    assert status.is_open is False
    assert status.reason == "Labour Day"


def test_krx_closes_on_last_trading_day_of_year():
    status = krx_market_day_status(date(2028, 12, 29))

    assert status.is_open is False
    assert status.reason == "KRX year-end closing day"


def test_configured_closure_covers_extraordinary_market_closings():
    status = krx_market_day_status(
        date(2026, 6, 4),
        configured_closed_dates="2026-06-04, 2026-12-01",
    )

    assert status.is_open is False
    assert status.reason == "configured market closure"


def test_batch_target_date_uses_batch_timezone():
    settings = SimpleNamespace(batch_timezone="Asia/Seoul")
    now = datetime(2026, 8, 17, 15, 30, tzinfo=timezone.utc)

    assert batch_target_date(settings, now) == date(2026, 8, 18)


def test_orchestrator_skips_before_creating_a_crawl_job(monkeypatch):
    settings = SimpleNamespace(
        batch_timezone="Asia/Seoul",
        market_closed_dates="",
    )
    monkeypatch.setattr("app.services.batch.orchestrator.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.batch_target_date", lambda _: date(2026, 8, 17)
    )

    result = BatchOrchestrator(source=None).run_daily_job()

    assert result["job_id"] is None
    assert result["skipped"] is True
    assert "holiday" in result["skip_reason"].lower()
    assert result["trade_date"] == "2026-08-17"


def test_legacy_runner_skips_before_creating_a_crawl_job(monkeypatch):
    settings = SimpleNamespace(
        batch_timezone="Asia/Seoul",
        market_closed_dates="",
    )
    context = build_memory_batch_context()
    monkeypatch.setattr("app.services.batch.run_daily_job.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.batch_target_date", lambda _: date(2026, 8, 17)
    )

    result = run_daily_job(context, source=None)

    assert result["skipped"] is True
    assert context.crawl_job_repository.get_latest() is None


def test_legacy_runner_preserves_an_explicit_trade_date_for_deterministic_replay(monkeypatch):
    settings = SimpleNamespace(
        batch_timezone="Asia/Seoul",
        market_closed_dates="",
        kiwoom_fallback_enabled=False,
        validation_enabled=False,
    )
    context = build_memory_batch_context()
    context.target_date = date(2025, 9, 17)
    monkeypatch.setattr("app.services.batch.run_daily_job.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.batch_target_date", lambda _: date(2026, 8, 23)
    )
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_symbols", lambda *_: [])
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_benchmarks", lambda *_: {})
    monkeypatch.setattr("app.services.batch.run_daily_job.sync_prices", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.batch.run_daily_job.calculate_rs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "app.services.batch.run_daily_job.notification_service.send_batch_success_sync",
        lambda **_kwargs: None,
    )

    result = run_daily_job(context, source=None)

    assert result["symbols"] == 0
    assert context.target_date == date(2025, 9, 17)


def test_orchestrator_uses_its_frozen_trade_date_for_price_steps(monkeypatch):
    from app.services.batch.orchestrator import BatchOrchestrator

    @contextmanager
    def fake_session_scope():
        yield object()

    context = SimpleNamespace(job_id=None, target_date=None, price_source=None)
    orchestrator = BatchOrchestrator(source=object())
    orchestrator.target_date = date(2025, 9, 17)
    monkeypatch.setattr("app.services.batch.orchestrator.session_scope", fake_session_scope)
    monkeypatch.setattr("app.services.batch.orchestrator.build_db_batch_context", lambda _: context)
    monkeypatch.setattr(
        "app.services.batch.orchestrator.batch_target_date", lambda _: date(2025, 9, 18)
    )

    result = orchestrator._execute_step("prices", lambda batch_context: batch_context.target_date)

    assert result == date(2025, 9, 17)


def test_main_skips_before_initializing_the_database(monkeypatch):
    from app import main_batch

    settings = SimpleNamespace(
        batch_timezone="Asia/Seoul",
        market_closed_dates="",
    )
    initialized = False

    def mark_initialized():
        nonlocal initialized
        initialized = True

    monkeypatch.setattr(main_batch, "get_settings", lambda: settings)
    monkeypatch.setattr(main_batch, "batch_target_date", lambda _: date(2026, 8, 17))
    monkeypatch.setattr(main_batch, "init_db", mark_initialized)

    main_batch.main([])

    assert initialized is False


def test_main_symbols_only_runs_universe_sync_without_full_price_batch(monkeypatch):
    from app import main_batch

    settings = SimpleNamespace(
        batch_timezone="Asia/Seoul",
        market_closed_dates="",
        kiwoom_fallback_enabled=False,
        repair_reconciler_enabled=False,
    )
    source = object()
    context = SimpleNamespace(
        universe_snapshot_id=123,
        universe_snapshot_status="completed",
    )
    initialized = False
    sync_calls = []

    def mark_initialized():
        nonlocal initialized
        initialized = True

    @contextmanager
    def fake_session_scope():
        yield object()

    def full_batch_must_not_run(*args, **kwargs):
        raise AssertionError("symbols-only must not run the full price batch")

    monkeypatch.setattr(main_batch, "get_settings", lambda: settings)
    monkeypatch.setattr(main_batch, "batch_target_date", lambda _: date(2026, 8, 18))
    monkeypatch.setattr(
        main_batch,
        "krx_market_day_status",
        lambda *args, **kwargs: SimpleNamespace(is_open=True, reason=None),
    )
    monkeypatch.setattr(main_batch, "init_db", mark_initialized)
    monkeypatch.setattr(main_batch, "NaverPriceSource", lambda: source)
    monkeypatch.setattr(main_batch, "session_scope", fake_session_scope, raising=False)
    monkeypatch.setattr(main_batch, "build_db_batch_context", lambda _: context, raising=False)
    monkeypatch.setattr(
        main_batch,
        "sync_symbols",
        lambda received_context, received_source: sync_calls.append(
            (received_context, received_source)
        ) or ["symbol"],
        raising=False,
    )
    monkeypatch.setattr(main_batch, "BatchOrchestrator", full_batch_must_not_run)

    main_batch.main(["--symbols-only"])

    assert initialized is True
    assert sync_calls == [(context, source)]

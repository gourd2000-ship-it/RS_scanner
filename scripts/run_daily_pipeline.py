#!/usr/bin/env python3
"""Plan or apply the locked close-of-day OHLCV/RS/indicator pipeline."""

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta, date
import fcntl
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.market_calendar import krx_market_day_status


ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def latest_completed_trade_date(settings, now=None):
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo('Asia/Seoul'))
    candidate = local.date()
    if local.time() < time(16, 30):
        candidate -= timedelta(days=1)
    while not krx_market_day_status(candidate, configured_closed_dates=settings.market_closed_dates).is_open:
        candidate -= timedelta(days=1)
    return candidate


def pipeline_failed(source, batch):
    validation = batch.get('validation') or {}
    return bool(
        source.get('failed') or batch.get('validation_blocked')
        or validation.get('validation_status') == 'blocked'
        or any(batch.get(kind) is not None and batch[kind].get('outcome') != 'completed'
               for kind in ('ema', 'volume_sma50', 'atr14'))
    )


@contextmanager
def pipeline_lock(engine):
    """Share the legacy host lock plus a DB lock across all pipeline stages."""
    from sqlalchemy import text
    (ROOT / 'logs').mkdir(exist_ok=True)
    with (ROOT / 'logs/daily_batch.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('daily_pipeline_already_running') from None
        with engine.connect() as connection:
            if connection.dialect.name == 'postgresql':
                if not connection.scalar(text('SELECT pg_try_advisory_lock(7426100901)')):
                    raise RuntimeError('daily_pipeline_already_running')
                connection.commit()
            try:
                yield
            finally:
                if connection.dialect.name == 'postgresql':
                    connection.execute(text('SELECT pg_advisory_unlock(7426100901)'))
                    connection.commit()


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='append source data and run the pipeline')
    parser.add_argument('--source-only', action='store_true', help='only refresh immutable indicator OHLCV')
    parser.add_argument('--scheduled', action='store_true', help='skip holidays and pre-close invocations')
    parser.add_argument('--target-date', type=date.fromisoformat)
    parser.add_argument('--manifest', type=Path, help='resume the exact saved source plan')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    # Parse dotenv without shell word splitting or exposing credentials. Explicit
    # process environment wins; production overrides the base file.
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env.production', override=False)
    load_dotenv(ROOT / '.env', override=False)
    os.environ.setdefault('APP_ENV', 'production')
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.core.database import engine, SessionLocal
    from app.services.batch.indicator_source_sync import plan_indicator_source, sync_indicator_source
    from app.crawler.kiwoom_client import KiwoomRestClient
    from app.crawler.sources.kiwoom_history import KiwoomHistoryRequest, iter_kiwoom_history
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    configure_logging()
    settings = get_settings()
    now = datetime.now(UTC)
    latest = latest_completed_trade_date(settings, now)
    today = now.astimezone(ZoneInfo('Asia/Seoul')).date()
    if args.scheduled and today != latest:
        logger.info('daily pipeline skipped: no completed market session today')
        return 0
    target_date = args.target_date or latest
    if target_date > latest or not krx_market_day_status(target_date, configured_closed_dates=settings.market_closed_dates).is_open:
        parser.error('--target-date must be a completed KRX trading day')
    output = args.output or ROOT / 'reports/operations' / f'daily_pipeline_{now:%Y%m%dT%H%M%SZ}.json'
    with pipeline_lock(engine):
        if args.manifest:
            plan = json.loads(args.manifest.read_text())
            if plan['target_date'] != target_date.isoformat():
                parser.error('manifest target date differs from requested date')
        else:
            with engine.connect() as connection:
                if connection.dialect.name == 'postgresql':
                    connection.execute(text('BEGIN READ ONLY'))
                with Session(bind=connection) as session:
                    plan = plan_indicator_source(session, target_date=target_date,
                                                 closed_dates=settings.market_closed_dates)
                connection.rollback()
        plan_path = output.with_name(output.stem + '.plan.json')
        _write(plan_path, plan)
        logger.info('indicator source plan targets=%s already_current=%s excluded=%s rows=%s manifest=%s',
                    len(plan['targets']), plan['already_current'], len(plan['excluded']),
                    plan['expected_new_rows'], plan['manifest_hash'])
        if not args.apply:
            _write(output, {'applied': False, 'manifest_hash': plan['manifest_hash'], 'plan_path': str(plan_path)})
            return 0
        client = KiwoomRestClient(settings=settings)

        def pages(target):
            return iter_kiwoom_history(KiwoomHistoryRequest(
                code=target['code'], start=date.fromisoformat(target['start']),
                end=target_date, base_date=plan['base_date'], market='KOSPI/KOSDAQ',
                adjustment_type='1', request_budget=2), client=client)

        with SessionLocal() as session:
            source = sync_indicator_source(session, plan, page_factory=pages)
        excluded_instruments = {
            entry['instrument_id'] for entry in plan['excluded'] if entry.get('instrument_id') is not None
        }
        excluded_instruments.update(
            entry['instrument_id'] for entry in source['failures'] if entry.get('instrument_id') is not None
        )
        source['excluded_instrument_ids'] = sorted(excluded_instruments)
        source['eligible_instrument_count'] = max(0, plan['series_instruments'] - len(excluded_instruments))
        if plan['series_instruments'] == 0:
            source['failed'] += 1
            source['failures'].append({'reason': 'no_existing_indicator_series'})
        report = {'applied': True, 'target_date': target_date.isoformat(),
                  'source': source, 'plan_path': str(plan_path)}
        _write(output, report)
        if args.source_only:
            return 2 if source['failed'] else 0
        from app.services.batch.orchestrator import BatchOrchestrator
        from app.crawler.sources.naver import NaverPriceSource
        batch = BatchOrchestrator(NaverPriceSource(),
            # The three indicators select only instruments with an immutable
            # Kiwoom observation for target_date. Naver validation still
            # controls RS publication, but does not discard verified Kiwoom
            # indicator evidence for the other instruments.
            indicator_requires_crawl_validation=False,
        ).run_daily_job(target_date=target_date)
        report['batch'] = batch
        _write(output, report)
        return 2 if pipeline_failed(source, batch) else 0


if __name__ == '__main__':
    raise SystemExit(main())

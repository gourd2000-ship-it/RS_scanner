import argparse
import logging

from app.core.database import init_db, session_scope
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.market_calendar import batch_target_date, krx_market_day_status
from app.crawler.sources.naver import NaverPriceSource
from app.services.batch.orchestrator import BatchOrchestrator
from app.services.batch.context import build_db_batch_context
from app.services.batch.sync_symbols import sync_symbols


logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RS Scanner 일일 배치")
    parser.add_argument(
        "--symbols-only",
        action="store_true",
        help="Naver universe snapshot과 심볼 동기화만 실행한다. 가격/RS는 실행하지 않는다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """배치 메인 엔트리포인트 - 체크포인트 시스템 사용"""
    configure_logging()
    args = parse_args(argv)
    settings = get_settings()
    target_date = batch_target_date(settings)
    market_status = krx_market_day_status(
        target_date,
        configured_closed_dates=settings.market_closed_dates,
    )
    if not market_status.is_open:
        logger.info(
            "skipping daily batch for %s: %s; no crawl job will be created",
            target_date,
            market_status.reason,
        )
        return

    init_db()
    source = NaverPriceSource()
    if settings.kiwoom_fallback_enabled or settings.repair_reconciler_enabled:
        logger.warning(
            "legacy Kiwoom fallback and repair reconciliation are disabled in the daily batch"
        )
    if args.symbols_only:
        with session_scope() as session:
            context = build_db_batch_context(session)
            symbols = sync_symbols(context, source)
            logger.info(
                "symbols-only summary: snapshot_id=%s status=%s symbols=%s",
                context.universe_snapshot_id,
                context.universe_snapshot_status,
                len(symbols),
            )
        return

    orchestrator = BatchOrchestrator(source)
    result = orchestrator.run_daily_job()

    logger.info("batch summary: %s", result)


if __name__ == "__main__":
    main()

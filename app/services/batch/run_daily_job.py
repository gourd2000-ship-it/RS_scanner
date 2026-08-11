import logging
from datetime import datetime

from app.core.config import get_settings
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource
from app.crawler.sources.eod import BulkEodSource
from app.crawler.sources.eod import EodCanaryPolicy
from app.services.batch.calculate_rs import calculate_rs
from app.services.batch.context import BatchContext
from app.services.batch.sync_benchmarks import sync_benchmarks
from app.services.batch.sync_eod import sync_eod_prices
from app.services.batch.sync_prices import PriceSyncResult, sync_prices
from app.services.batch.sync_symbols import sync_symbols
from app.services.validation.data_quality import validate_crawl_job


logger = logging.getLogger(__name__)
notification_service = get_notification_service()


def run_daily_job(
    context: BatchContext,
    source: PriceSource,
    eod_source: BulkEodSource | None = None,
) -> dict[str, object]:
    logger.info("starting daily batch")
    started_at = datetime.utcnow()
    context.price_source = source

    # 작업 추적 시작 (선택적)
    job = None
    job_id = None
    if context.crawl_job_repository:
        job = context.crawl_job_repository.create_job("daily_full")
        job_id = job.id
        context.job_id = job_id
        logger.info(f"created crawl job: {job_id}")

    try:
        symbols = sync_symbols(context, source)
        benchmarks = sync_benchmarks(context, source)
        use_eod = eod_source is not None and get_settings().eod_provider_enabled
        prices = (
            sync_eod_prices(
                context,
                eod_source,
                fallback_source=source,
                canary_policy=EodCanaryPolicy.from_settings(get_settings()),
            )
            if use_eod
            else sync_prices(context, source)
        )
        validation_result = None
        validation_blocked = False
        target_date = None
        settings = get_settings()
        if (
            context.session is not None
            and context.job_id is not None
            and settings.validation_enabled
        ):
            validation_result = validate_crawl_job(
                context.session,
                context.job_id,
                mode=settings.validation_mode,
            )
            context.validation_run_id = validation_result.run.id
            context.validation_status = validation_result.run.validation_status
            target_date = validation_result.run.trade_date
            context.target_date = target_date
            validation_blocked = (
                settings.validation_mode == "enforce" and validation_result.would_block
            )

        rs_results = (
            {}
            if validation_blocked
            else calculate_rs(context, target_date=target_date)
        )

        # 가격 단계 결과에서 실제 종목별 통계를 계산한다.
        price_stats = prices if isinstance(prices, PriceSyncResult) else None
        universe_degraded = context.universe_snapshot_status in {"partial", "failed"}
        symbols_total = price_stats.target_count if price_stats else len(symbols)
        symbols_succeeded = price_stats.succeeded_count if price_stats else symbols_total
        symbols_failed = price_stats.unsuccessful_count if price_stats else 0
        job_status = (
            "completed_with_errors"
            if symbols_failed or universe_degraded or validation_blocked
            else "completed"
        )
        job_message = (
            "Daily batch completed with errors"
            if symbols_failed or universe_degraded or validation_blocked
            else "Daily batch completed successfully"
        )

        # 작업 완료 기록
        if context.crawl_job_repository and job_id:
            context.crawl_job_repository.finish_job(
                job_id=job_id,
                status=job_status,
                symbols_total=symbols_total,
                symbols_succeeded=symbols_succeeded,
                symbols_failed=symbols_failed,
                message=job_message,
            )
            logger.info(f"finished crawl job: {job_id}")

        duration = (datetime.utcnow() - started_at).total_seconds()
        if symbols_failed or universe_degraded:
            notification_service.send_batch_failure_sync(
                job_type="daily_full",
                error_message=job_message,
                failed_count=symbols_failed,
                total_count=symbols_total,
                started_at=started_at,
            )
        else:
            notification_service.send_batch_success_sync(
                job_type="daily_full",
                total_count=symbols_total,
                duration_seconds=duration,
            )

        logger.info("finished daily batch")
        return {
            "job_id": job_id,
            "symbols": symbols_total,
            "benchmarks": {market: len(rows) for market, rows in benchmarks.items()},
            "prices": {code: len(rows) for code, rows in prices.items()},
            "rs_results": {market: len(rows) for market, rows in rs_results.items()},
            "validation": validation_result.to_dict() if validation_result else None,
            "validation_blocked": validation_blocked,
        }
    except Exception as e:
        error_message = str(e)
        symbols_total = 0
        symbols_failed = 0

        # 작업 실패 기록
        if context.crawl_job_repository and job_id:
            context.crawl_job_repository.finish_job(
                job_id=job_id,
                status="failed",
                symbols_total=symbols_total,
                symbols_succeeded=0,
                symbols_failed=symbols_failed,
                message=f"Batch failed: {error_message}",
            )
            logger.error(f"crawl job {job_id} failed: {e}")

        # 실패 알림 전송
        notification_service.send_batch_failure_sync(
            job_type="daily_full",
            error_message=error_message,
            failed_count=symbols_failed,
            total_count=symbols_total,
            started_at=started_at,
        )

        raise


def run_sync_symbols_only(context: BatchContext, source: PriceSource):
    return sync_symbols(context, source)


def run_calculate_rs_only(context: BatchContext):
    return calculate_rs(context)

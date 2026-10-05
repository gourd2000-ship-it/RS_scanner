import logging
from datetime import date, datetime

from app.core.config import get_settings
from app.core.market_calendar import batch_target_date, krx_market_day_status
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource
from app.crawler.sources.eod import BulkEodSource
from app.crawler.sources.eod import EodCanaryPolicy
from app.crawler.sources.krx import KrxUniverseSource
from app.services.batch.calculate_rs import calculate_rs
from app.services.batch.context import BatchContext
from app.services.batch.sync_benchmarks import sync_benchmarks
from app.services.batch.sync_eod import sync_eod_prices
from app.services.batch.sync_prices import PriceSyncResult, sync_prices
from app.services.batch.sync_krx_universe import sync_krx_universe
from app.services.batch.sync_symbols import sync_symbols
from app.services.batch.ema_adapter import (
    EmaBatchOutcome,
    calculate_daily_ema,
    completed_ema_outcome,
    ema_enabled,
    record_ema_checkpoint,
)
from app.services.batch.volume_adapter import (
    VolumeBatchOutcome,
    calculate_daily_volume_sma50,
    completed_volume_outcome,
    record_volume_checkpoint,
    volume_sma50_enabled,
)
from app.services.validation.data_quality import validate_crawl_job
from app.services.validation.report import write_validation_report
from app.core.metrics import increment_metric
from app.services.monitoring.crawl_quality_report import ensure_crawl_quality_report


logger = logging.getLogger(__name__)
notification_service = get_notification_service()


def run_daily_job(
    context: BatchContext,
    source: PriceSource,
    eod_source: BulkEodSource | None = None,
    fallback_source: PriceSource | None = None,
    krx_source: KrxUniverseSource | None = None,
) -> dict[str, object]:
    logger.info("starting daily batch")
    started_at = datetime.utcnow()
    settings = get_settings()
    if not isinstance(context.target_date, date):
        context.target_date = batch_target_date(settings)
    market_status = krx_market_day_status(
        context.target_date,
        configured_closed_dates=settings.market_closed_dates,
    )
    if not market_status.is_open:
        logger.info("skipping daily batch for %s: %s", context.target_date, market_status.reason)
        return {
            "job_id": None,
            "skipped": True,
            "skip_reason": market_status.reason,
            "trade_date": context.target_date.isoformat(),
        }
    if fallback_source is not None or settings.kiwoom_fallback_enabled:
        logger.warning("legacy Kiwoom fallback is ignored by the daily batch")
    context.price_source = source

    # 작업 추적 시작 (선택적)
    job = None
    job_id = None
    if context.job_id is not None:
        job_id = context.job_id
        logger.info("using existing crawl job: %s", job_id)
    elif context.crawl_job_repository:
        job = context.crawl_job_repository.create_job("daily_full")
        job_id = job.id
        context.job_id = job_id
        logger.info(f"created crawl job: {job_id}")

    try:
        # KRX is shadow-only: its failure is retained on a separate snapshot
        # and never changes the Naver symbol or price path below.
        if context.krx_universe_repository is not None and (
            krx_source is not None or settings.krx_shadow_ingestion_enabled
        ):
            sync_krx_universe(context, krx_source or KrxUniverseSource())

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
            else sync_prices(
                context,
                source,
                fallback_source=None,
                fallback_max_requests=None,
            )
        )
        validation_result = None
        validation_blocked = False
        target_date = None
        validation_report_path = None
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
            try:
                validation_report_path = str(write_validation_report(validation_result))
                logger.info("wrote validation report: %s", validation_report_path)
            except Exception:
                logger.exception("failed to write validation report for job %s", job_id)
            validation_blocked = (
                settings.validation_mode == "enforce" and validation_result.would_block
            )

        rs_results = (
            {}
            if validation_blocked
            else calculate_rs(context, target_date=target_date)
        )

        # EMA is optional and runs only after the clean validation decision and
        # RS publication.  A missing policy or a calculation problem is
        # retained as EMA evidence without discarding otherwise valid RS.
        ema_result: EmaBatchOutcome | None = None
        if ema_enabled(settings):
            ema_result = None if validation_blocked else completed_ema_outcome(context)
            if ema_result is None:
                try:
                    ema_result = (
                        EmaBatchOutcome.skipped("validation_gate_blocked")
                        if validation_blocked
                        else calculate_daily_ema(
                            context,
                            target_date=target_date or context.target_date,
                            settings=settings,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - independent optional steps.
                    ema_result = EmaBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)
                record_ema_checkpoint(context, ema_result)

        volume_result: VolumeBatchOutcome | None = None
        if volume_sma50_enabled(settings):
            if validation_blocked or validation_result is None:
                volume_result = VolumeBatchOutcome.skipped(
                    "validation_gate_blocked" if validation_blocked else "validation_unavailable"
                )
                record_volume_checkpoint(context, volume_result, settings=settings)
            else:
                volume_result = completed_volume_outcome(context, settings=settings)
            if volume_result is None:
                try:
                    volume_result = calculate_daily_volume_sma50(
                        context,
                        target_date=target_date or context.target_date,
                        settings=settings,
                    )
                except Exception as exc:  # noqa: BLE001 - preserve EMA and RS.
                    volume_result = VolumeBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)
                record_volume_checkpoint(context, volume_result, settings=settings)

        indicator_errors = any(result is not None and result.has_errors for result in (ema_result, volume_result))

        # 가격 단계 결과에서 실제 종목별 통계를 계산한다.
        price_stats = prices if isinstance(prices, PriceSyncResult) else None
        universe_degraded = (
            context.universe_snapshot_status in {"partial", "failed"}
            or context.krx_universe_snapshot_status in {"partial", "failed"}
        )
        symbols_total = price_stats.target_count if price_stats else len(symbols)
        symbols_succeeded = price_stats.succeeded_count if price_stats else symbols_total
        symbols_failed = price_stats.unsuccessful_count if price_stats else 0
        job_status = (
            "completed_with_errors"
            if symbols_failed or universe_degraded or validation_blocked or indicator_errors
            else "completed"
        )
        job_message = (
            "Daily batch completed with errors"
            if symbols_failed or universe_degraded or validation_blocked or indicator_errors
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
            if context.session is not None:
                try:
                    ensure_crawl_quality_report(context.session, crawl_job_id=job_id)
                except Exception:  # noqa: BLE001
                    increment_metric("quality_report_write_error")
                    logger.exception("failed to create crawl quality report for job %s", job_id)

        duration = (datetime.utcnow() - started_at).total_seconds()
        if symbols_failed or universe_degraded or validation_blocked or indicator_errors:
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
            "validation_report": validation_report_path,
            "validation_blocked": validation_blocked,
            "ema": ema_result.to_dict() if ema_result is not None else None,
            "volume_sma50": volume_result.to_dict() if volume_result is not None else None,
            "krx_universe_snapshot_id": context.krx_universe_snapshot_id,
            "krx_universe_snapshot_status": context.krx_universe_snapshot_status,
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
            if context.session is not None:
                try:
                    ensure_crawl_quality_report(context.session, crawl_job_id=job_id)
                except Exception:  # noqa: BLE001
                    increment_metric("quality_report_write_error")
                    logger.exception("failed to create crawl quality report for job %s", job_id)

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

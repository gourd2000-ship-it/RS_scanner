import logging

from app.crawler.sources.base import PriceSource
from app.services.batch.calculate_rs import calculate_rs
from app.services.batch.context import BatchContext
from app.services.batch.sync_benchmarks import sync_benchmarks
from app.services.batch.sync_prices import sync_prices
from app.services.batch.sync_symbols import sync_symbols


logger = logging.getLogger(__name__)


def run_daily_job(context: BatchContext, source: PriceSource) -> dict[str, object]:
    logger.info("starting daily batch")

    # 작업 추적 시작 (선택적)
    job = None
    job_id = None
    if context.crawl_job_repository:
        job = context.crawl_job_repository.create_job("daily_full")
        job_id = job.id
        logger.info(f"created crawl job: {job_id}")

    try:
        symbols = sync_symbols(context, source)
        benchmarks = sync_benchmarks(context, source)
        prices = sync_prices(context, source)
        rs_results = calculate_rs(context)

        # 통계 계산
        symbols_total = len(symbols)
        symbols_succeeded = symbols_total
        symbols_failed = 0

        # 작업 완료 기록
        if context.crawl_job_repository and job_id:
            context.crawl_job_repository.finish_job(
                job_id=job_id,
                status="completed",
                symbols_total=symbols_total,
                symbols_succeeded=symbols_succeeded,
                symbols_failed=symbols_failed,
                message="Daily batch completed successfully",
            )
            logger.info(f"finished crawl job: {job_id}")

        logger.info("finished daily batch")
        return {
            "job_id": job_id,
            "symbols": len(symbols),
            "benchmarks": {market: len(rows) for market, rows in benchmarks.items()},
            "prices": {code: len(rows) for code, rows in prices.items()},
            "rs_results": {market: len(rows) for market, rows in rs_results.items()},
        }
    except Exception as e:
        # 작업 실패 기록
        if context.crawl_job_repository and job_id:
            context.crawl_job_repository.finish_job(
                job_id=job_id,
                status="failed",
                symbols_total=0,
                symbols_succeeded=0,
                symbols_failed=0,
                message=f"Batch failed: {str(e)}",
            )
            logger.error(f"crawl job {job_id} failed: {e}")
        raise


def run_sync_symbols_only(context: BatchContext, source: PriceSource):
    return sync_symbols(context, source)


def run_calculate_rs_only(context: BatchContext):
    return calculate_rs(context)

"""배치 작업 오케스트레이터 - 단계별 트랜잭션 관리 및 체크포인트 시스템"""

import logging
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource
from app.crawler.sources.eod import BulkEodSource
from app.crawler.sources.eod import EodCanaryPolicy
from app.services.batch.calculate_rs import calculate_rs
from app.services.batch.context import build_db_batch_context, BatchContext
from app.services.batch.sync_benchmarks import sync_benchmarks
from app.services.batch.sync_eod import sync_eod_prices
from app.services.batch.sync_prices import PriceSyncResult, sync_prices
from app.services.batch.sync_symbols import sync_symbols
from app.core.config import get_settings
from app.repositories.data_quality_repository import DataQualityRepository
from app.services.validation.data_quality import ValidationResult, validate_crawl_job


logger = logging.getLogger(__name__)
notification_service = get_notification_service()


class BatchOrchestrator:
    """배치 오케스트레이터 - 단계별 트랜잭션 분리 및 체크포인트 관리"""

    def __init__(
        self,
        source: PriceSource,
        eod_source: BulkEodSource | None = None,
    ):
        self.source = source
        self.eod_source = eod_source
        self.job_id: int | None = None
        self.universe_snapshot_status: str | None = None
        self.started_at: datetime = datetime.utcnow()

    def run_daily_job(self) -> dict[str, Any]:
        """일일 배치 작업 실행 (단계별 트랜잭션)"""
        logger.info("starting daily batch with checkpointing")

        # Step 0: 작업 생성 (별도 트랜잭션)
        self._create_job()

        try:
            # Step 1: 심볼 동기화
            symbols = self._run_step(
                step_name="symbols",
                step_func=lambda ctx: sync_symbols(ctx, self.source),
                description="심볼 동기화",
            )

            # Step 2: 벤치마크 동기화
            benchmarks = self._run_step(
                step_name="benchmarks",
                step_func=lambda ctx: sync_benchmarks(ctx, self.source),
                description="벤치마크 동기화",
            )

            # Step 3: 가격 데이터 동기화
            prices = self._run_step(
                step_name="prices",
                step_func=lambda ctx: (
                    sync_eod_prices(
                        ctx,
                        self.eod_source,
                        fallback_source=self.source,
                        canary_policy=EodCanaryPolicy.from_settings(get_settings()),
                    )
                    if self.eod_source is not None and get_settings().eod_provider_enabled
                    else sync_prices(ctx, self.source)
                ),
                description="가격 데이터 동기화",
            )

            # Step 4: 데이터 품질 검증.  report_only에서는 기존 RS 동작을
            # 유지하지만, enforce에서는 blocked validation 결과를 publish로
            # 전파하지 않는다.
            validation_result = None
            if get_settings().validation_enabled:
                validation_result = self._run_step(
                    step_name="validation",
                    step_func=lambda ctx: validate_crawl_job(
                        ctx.session,
                        self.job_id,
                        mode=get_settings().validation_mode,
                    ),
                    description="데이터 품질 검증",
                )
            validation_blocked = (
                isinstance(validation_result, ValidationResult)
                and get_settings().validation_mode == "enforce"
                and validation_result.would_block
            )

            # Step 5: RS 계산
            if validation_blocked:
                self._block_step_checkpoint("rs", "validation gate blocked RS publish")
                rs_results = {}
            else:
                rs_results = self._run_step(
                    step_name="rs",
                    step_func=calculate_rs,
                    description="RS 계산",
                )

            price_stats = prices if isinstance(prices, PriceSyncResult) else None
            universe_degraded = self.universe_snapshot_status in {"partial", "failed"}
            symbols_total = price_stats.target_count if price_stats else (len(symbols) if symbols else 0)
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

            # Step 5: 작업 완료 (별도 트랜잭션)
            self._finish_job(
                status=job_status,
                symbols_total=symbols_total,
                symbols_succeeded=symbols_succeeded,
                symbols_failed=symbols_failed,
                message=job_message,
            )

            duration = (datetime.utcnow() - self.started_at).total_seconds()
            if symbols_failed or universe_degraded:
                notification_service.send_batch_failure_sync(
                    job_type="daily_full",
                    error_message=job_message,
                    failed_count=symbols_failed,
                    total_count=symbols_total,
                    started_at=self.started_at,
                )
            else:
                notification_service.send_batch_success_sync(
                    job_type="daily_full",
                    total_count=symbols_total,
                    duration_seconds=duration,
                )

            logger.info("finished daily batch")
            return {
                "job_id": self.job_id,
                "symbols": symbols_total,
                "benchmarks": {market: len(rows) for market, rows in benchmarks.items()} if benchmarks else {},
                "prices": {code: len(rows) for code, rows in prices.items()} if prices else {},
                "rs_results": {market: len(rows) for market, rows in rs_results.items()} if rs_results else {},
                "validation": validation_result.to_dict() if isinstance(validation_result, ValidationResult) else None,
                "validation_blocked": validation_blocked,
            }

        except Exception as e:
            logger.error(f"batch failed: {e}", exc_info=True)

            # 작업 실패 기록
            self._finish_job(
                status="failed",
                symbols_total=0,
                symbols_succeeded=0,
                symbols_failed=0,
                message=f"Batch failed: {str(e)}",
            )

            # 실패 알림
            notification_service.send_batch_failure_sync(
                job_type="daily_full",
                error_message=str(e),
                failed_count=0,
                total_count=0,
                started_at=self.started_at,
            )

            raise

    def _create_job(self) -> None:
        """작업 생성 (별도 트랜잭션)"""
        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.crawl_job_repository:
                job = context.crawl_job_repository.create_job("daily_full")
                self.job_id = job.id
                logger.info(f"created crawl job: {self.job_id}")

                # 각 단계에 대한 체크포인트 초기화
                if context.checkpoint_repository:
                    for step_name in ["symbols", "benchmarks", "prices", "validation", "rs"]:
                        context.checkpoint_repository.create_checkpoint(
                            job_id=self.job_id,
                            step_name=step_name,
                            status="pending",
                        )
                    logger.info(f"initialized checkpoints for job {self.job_id}")

    def _finish_job(
        self,
        status: str,
        symbols_total: int,
        symbols_succeeded: int,
        symbols_failed: int,
        message: str,
    ) -> None:
        """작업 완료 (별도 트랜잭션)"""
        if not self.job_id:
            return

        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.crawl_job_repository:
                context.crawl_job_repository.finish_job(
                    job_id=self.job_id,
                    status=status,
                    symbols_total=symbols_total,
                    symbols_succeeded=symbols_succeeded,
                    symbols_failed=symbols_failed,
                    message=message,
                )
                logger.info(f"finished crawl job {self.job_id}: {status}")

    def _run_step(
        self,
        step_name: str,
        step_func: Callable[[BatchContext], Any],
        description: str,
    ) -> Any:
        """단계 실행 (독립적인 트랜잭션)"""
        # 체크포인트 확인: 이미 완료된 단계는 스킵
        if self._is_step_completed(step_name):
            logger.info(f"skipping already completed step: {step_name}")
            return self._get_step_result(step_name)

        logger.info(f"starting step: {step_name} ({description})")

        # 단계 시작 기록 (별도 트랜잭션)
        self._start_step_checkpoint(step_name)

        try:
            # 단계 실행 (별도 트랜잭션)
            result = self._execute_step(step_name, step_func)

            # 단계 완료 기록 (별도 트랜잭션)
            self._complete_step_checkpoint(step_name, result)

            logger.info(f"completed step: {step_name}")
            return result

        except Exception as e:
            logger.error(f"step {step_name} failed: {e}", exc_info=True)

            # 단계 실패 기록 (별도 트랜잭션)
            self._fail_step_checkpoint(step_name, str(e))

            raise

    def _is_step_completed(self, step_name: str) -> bool:
        """단계 완료 여부 확인"""
        if not self.job_id:
            return False

        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                return context.checkpoint_repository.is_step_completed(self.job_id, step_name)
        return False

    def _get_step_result(self, step_name: str) -> Any:
        """완료된 단계의 결과 조회 (DB에서 로드)"""
        logger.info(f"loading result for completed step: {step_name}")
        if step_name == "validation" and self.job_id:
            with session_scope() as session:
                repository = DataQualityRepository(session)
                run = repository.latest_validation_run(crawl_job_id=self.job_id)
                if run is not None:
                    return ValidationResult(run=run, cases=[], metrics=run.metrics or {})
        return None

    def _start_step_checkpoint(self, step_name: str) -> None:
        """단계 시작 체크포인트 기록"""
        if not self.job_id:
            return

        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                context.checkpoint_repository.start_step(self.job_id, step_name)

    def _complete_step_checkpoint(self, step_name: str, result: Any) -> None:
        """단계 완료 체크포인트 기록"""
        if not self.job_id:
            return

        # 결과 크기 계산
        items_processed = 0
        items_failed = 0
        checkpoint_status = "completed"
        if isinstance(result, PriceSyncResult):
            items_processed = result.target_count
            items_failed = result.unsuccessful_count
            if items_failed:
                checkpoint_status = "completed_with_errors"
        elif isinstance(result, ValidationResult):
            items_processed = result.run.expected_symbols
            items_failed = result.run.error_count + result.run.critical_count
            if result.would_block or result.run.warning_count:
                checkpoint_status = "completed_with_errors"
        elif isinstance(result, list):
            items_processed = len(result)
        elif isinstance(result, dict):
            items_processed = sum(len(v) if isinstance(v, list) else 1 for v in result.values())

        # 소요 시간 계산 (체크포인트에서 started_at 조회)
        duration_seconds = 0.0
        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                checkpoint = context.checkpoint_repository.get_checkpoint(self.job_id, step_name)
                if checkpoint and checkpoint.started_at:
                    duration_seconds = (datetime.utcnow() - checkpoint.started_at).total_seconds()

                context.checkpoint_repository.complete_step(
                    job_id=self.job_id,
                    step_name=step_name,
                    status=checkpoint_status,
                    items_processed=items_processed,
                    items_failed=items_failed,
                )

        # 단계 완료 알림 전송
        try:
            notification_service.send_step_completed_sync(
                step_name=step_name,
                items_count=items_processed,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            logger.error(f"Failed to send step completion notification for {step_name}: {e}")

    def _fail_step_checkpoint(self, step_name: str, error_message: str) -> None:
        """단계 실패 체크포인트 기록"""
        if not self.job_id:
            return

        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                context.checkpoint_repository.fail_step(
                    job_id=self.job_id,
                    step_name=step_name,
                    error_message=error_message,
                )

    def _block_step_checkpoint(self, step_name: str, message: str) -> None:
        """Record a policy block without treating it as an infrastructure crash."""
        if not self.job_id:
            return
        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                context.checkpoint_repository.complete_step(
                    job_id=self.job_id,
                    step_name=step_name,
                    status="blocked",
                    step_metadata=message,
                )

    def _execute_step(self, step_name: str, step_func: Callable[[BatchContext], Any]) -> Any:
        """단계 실행 (별도 트랜잭션)"""
        with session_scope() as session:
            context = build_db_batch_context(session)
            context.job_id = self.job_id
            context.price_source = self.source
            if step_name == "rs" and self.job_id:
                validation_run = DataQualityRepository(session).latest_validation_run(
                    crawl_job_id=self.job_id
                )
                if validation_run is not None:
                    context.validation_run_id = validation_run.id
                    context.validation_status = validation_run.validation_status
                    context.target_date = validation_run.trade_date
            result = step_func(context)
            if step_name == "symbols":
                self.universe_snapshot_status = context.universe_snapshot_status
            return result

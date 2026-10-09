"""배치 작업 오케스트레이터 - 단계별 트랜잭션 관리 및 체크포인트 시스템"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.core.notification import get_notification_service
from app.crawler.sources.base import PriceSource
from app.crawler.sources.eod import BulkEodSource
from app.crawler.sources.eod import EodCanaryPolicy
from app.crawler.sources.krx import KrxUniverseSource
from app.services.batch.calculate_rs import calculate_rs
from app.services.batch.context import build_db_batch_context, BatchContext
from app.services.batch.indicator_validation import indicator_validation_skip_reason
from app.services.batch.sync_benchmarks import sync_benchmarks
from app.services.batch.sync_eod import sync_eod_prices
from app.services.batch.sync_prices import PriceSyncResult, sync_prices
from app.services.batch.sync_krx_universe import KrxUniverseSyncResult, sync_krx_universe
from app.services.batch.sync_symbols import sync_symbols
from app.services.batch.ema_adapter import (
    EmaBatchOutcome,
    calculate_daily_ema,
    ema_enabled,
    record_ema_checkpoint,
)
from app.services.batch.volume_adapter import (
    VOLUME_STEP_NAME,
    VolumeBatchOutcome,
    calculate_daily_volume_sma50,
    completed_volume_outcome,
    record_volume_checkpoint,
    volume_sma50_enabled,
)
from app.services.batch.atr_adapter import (
    ATR_STEP_NAME,
    AtrBatchOutcome,
    atr14_enabled,
    calculate_daily_atr14,
    completed_atr_outcome,
    record_atr_checkpoint,
)
from app.core.config import get_settings
from app.core.metrics import increment_metric
from app.core.market_calendar import batch_target_date, krx_market_day_status
from app.repositories.data_quality_repository import DataQualityRepository
from app.services.monitoring.crawl_quality_report import ensure_crawl_quality_report
from app.services.monitoring.reconciliation_report import write_reconciliation_report
from app.services.monitoring.universe_reconciliation import build_universe_reconciliation_report
from app.services.validation.data_quality import ValidationResult, validate_crawl_job
from app.services.validation.report import write_validation_report


logger = logging.getLogger(__name__)
notification_service = get_notification_service()


class BatchOrchestrator:
    """배치 오케스트레이터 - 단계별 트랜잭션 분리 및 체크포인트 관리"""

    def __init__(
        self,
        source: PriceSource,
        eod_source: BulkEodSource | None = None,
        fallback_source: PriceSource | None = None,
        krx_source: KrxUniverseSource | None = None,
    ):
        self.source = source
        self.eod_source = eod_source
        self.krx_source = krx_source
        # Keep the argument temporarily for legacy call compatibility, but do
        # not retain or use it.  A daily crawl must not become an automatic
        # Kiwoom (or any other) fallback path.
        if fallback_source is not None:
            logger.warning("legacy fallback_source is ignored by the daily batch")
        self.fallback_source: PriceSource | None = None
        self.job_id: int | None = None
        self.universe_snapshot_status: str | None = None
        self.universe_snapshot_id: int | None = None
        self.krx_universe_snapshot_status: str | None = None
        self.started_at: datetime = datetime.utcnow()
        self.target_date: date | None = None

    def run_daily_job(self) -> dict[str, Any]:
        """일일 배치 작업 실행 (단계별 트랜잭션)"""
        logger.info("starting daily batch with checkpointing")

        settings = get_settings()
        target_date = batch_target_date(settings)
        self.target_date = target_date
        market_status = krx_market_day_status(
            target_date,
            configured_closed_dates=settings.market_closed_dates,
        )
        if not market_status.is_open:
            logger.info("skipping daily batch for %s: %s", target_date, market_status.reason)
            return {
                "job_id": None,
                "skipped": True,
                "skip_reason": market_status.reason,
                "trade_date": target_date.isoformat(),
            }

        # Step 0: 작업 생성 (별도 트랜잭션)
        self._create_job()

        try:
            # Step 1: KRX shadow snapshot.  This intentionally precedes the
            # Naver path but does not decide its target set.
            if settings.krx_shadow_ingestion_enabled:
                self._run_step(
                    step_name="krx_shadow",
                    step_func=lambda ctx: sync_krx_universe(
                        ctx, self.krx_source or KrxUniverseSource()
                    ),
                    description="KRX shadow universe 동기화",
                )

            # Step 2: 심볼 동기화
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
                    else sync_prices(
                        ctx,
                        self.source,
                        fallback_source=None,
                        fallback_max_requests=None,
                    )
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
            indicator_validation_reason = indicator_validation_skip_reason(validation_result)

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

            # EMA follows validation and RS.  Its evidence is optional and a
            # failed/blocked EMA pass must never retract RS that was already
            # persisted for this crawl job.
            ema_result: EmaBatchOutcome | None = None
            if ema_enabled(settings):
                if validation_blocked:
                    ema_result = EmaBatchOutcome.skipped("validation_gate_blocked")
                    self._record_ema_outcome(ema_result)
                else:
                    try:
                        ema_result = self._run_step(
                            step_name="ema",
                            step_func=lambda ctx: calculate_daily_ema(
                                ctx,
                                target_date=self.target_date or batch_target_date(settings),
                                settings=settings,
                            ),
                            description="EMA 계산",
                        )
                    except Exception as exc:  # noqa: BLE001 - Volume runs independently.
                        ema_result = EmaBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)
                        self._record_ema_outcome(ema_result)

            volume_result: VolumeBatchOutcome | None = None
            if volume_sma50_enabled(settings):
                if indicator_validation_reason is not None:
                    volume_result = VolumeBatchOutcome.skipped(indicator_validation_reason)
                    self._record_volume_outcome(volume_result)
                else:
                    try:
                        volume_result = self._run_step(
                            step_name=VOLUME_STEP_NAME,
                            step_func=lambda ctx: calculate_daily_volume_sma50(
                                ctx,
                                target_date=self.target_date or batch_target_date(settings),
                                settings=settings,
                            ),
                            description="Volume MA50 계산",
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve EMA and RS.
                        volume_result = VolumeBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)
                        self._record_volume_outcome(volume_result)

            atr_result: AtrBatchOutcome | None = None
            if atr14_enabled(settings):
                if indicator_validation_reason is not None:
                    atr_result = AtrBatchOutcome.skipped(indicator_validation_reason)
                    self._record_atr_outcome(atr_result)
                else:
                    try:
                        atr_result = self._run_step(
                            step_name=ATR_STEP_NAME,
                            step_func=lambda ctx: calculate_daily_atr14(
                                ctx, target_date=self.target_date or batch_target_date(settings), settings=settings,
                            ),
                            description="ATR14 계산",
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve completed optional indicators.
                        atr_result = AtrBatchOutcome.failure(processed=0, failed=1, reason=type(exc).__name__)
                        self._record_atr_outcome(atr_result)

            indicator_errors = any(
                result is not None and result.has_errors for result in (ema_result, volume_result, atr_result)
            )

            price_stats = prices if isinstance(prices, PriceSyncResult) else None
            universe_degraded = (
                self.universe_snapshot_status in {"partial", "failed"}
                or self.krx_universe_snapshot_status in {"partial", "failed"}
            )
            symbols_total = price_stats.target_count if price_stats else (len(symbols) if symbols else 0)
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

            # Step 5: 작업 완료 (별도 트랜잭션)
            self._finish_job(
                status=job_status,
                symbols_total=symbols_total,
                symbols_succeeded=symbols_succeeded,
                symbols_failed=symbols_failed,
                message=job_message,
            )
            reconciliation_report_path = (
                self._write_krx_reconciliation_report()
                if settings.krx_shadow_ingestion_enabled
                else None
            )

            duration = (datetime.utcnow() - self.started_at).total_seconds()
            if symbols_failed or universe_degraded or validation_blocked or indicator_errors:
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
                "ema": ema_result.to_dict() if ema_result is not None else None,
                "volume_sma50": volume_result.to_dict() if volume_result is not None else None,
                "atr14": atr_result.to_dict() if atr_result is not None else None,
                "reconciliation_report": str(reconciliation_report_path)
                if reconciliation_report_path is not None
                else None,
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
            if settings.krx_shadow_ingestion_enabled:
                self._write_krx_reconciliation_report()

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
        if self.job_id is not None:
            logger.info("using existing crawl job: %s", self.job_id)
            return
        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.crawl_job_repository:
                job = context.crawl_job_repository.create_job("daily_full")
                self.job_id = job.id
                logger.info(f"created crawl job: {self.job_id}")

                # 각 단계에 대한 체크포인트 초기화
                if context.checkpoint_repository:
                    step_names = ["krx_shadow", "symbols", "benchmarks", "prices", "validation", "rs"]
                    if ema_enabled():
                        step_names.append("ema")
                    if volume_sma50_enabled():
                        step_names.append(VOLUME_STEP_NAME)
                    if atr14_enabled():
                        step_names.append(ATR_STEP_NAME)
                    for step_name in step_names:
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

        # A report is deliberately written in a separate transaction.  Its
        # failure must never rewrite a completed/failed crawl job outcome.
        try:
            with session_scope() as session:
                report = ensure_crawl_quality_report(session, crawl_job_id=self.job_id)
                logger.info("created crawl quality report %s for job %s", report.id, self.job_id)
        except Exception:  # noqa: BLE001
            increment_metric("quality_report_write_error")
            logger.exception("failed to create crawl quality report for job %s", self.job_id)

    def _write_krx_reconciliation_report(self) -> Path | None:
        """Write reconciliation evidence after the crawl is committed.

        This is intentionally post-commit and read-only so a local report write
        problem cannot change an otherwise completed batch outcome.
        """
        if self.job_id is None:
            return None
        try:
            with session_scope() as session:
                report = build_universe_reconciliation_report(session)
            generated_at = datetime.now(ZoneInfo("UTC"))
            output = write_reconciliation_report(
                report,
                output_dir=Path("reports/krx_universe"),
                report_stem=(
                    "krx_universe_reconciliation_"
                    f"{generated_at.strftime('%Y%m%d_%H%M%S')}_job{self.job_id}"
                ),
                generated_at=generated_at,
            )
            logger.info("wrote KRX/Naver reconciliation report: %s", output)
            return output
        except Exception:  # noqa: BLE001 - reporting must not alter batch state
            increment_metric("krx_reconciliation_report_write_error")
            logger.exception("failed to write KRX reconciliation report for job %s", self.job_id)
            return None

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

            if step_name == "validation" and isinstance(result, ValidationResult):
                try:
                    report_path = write_validation_report(result)
                    logger.info("wrote validation report: %s", report_path)
                except Exception:
                    # Validation state is already persisted.  A local report
                    # write failure must not turn a data-quality result into
                    # a crawler/RS failure.
                    logger.exception("failed to write validation report for job %s", self.job_id)

            # 단계 완료 기록 (별도 트랜잭션)
            self._complete_step_checkpoint(step_name, result)

            logger.info(f"completed step: {step_name}")
            return result

        except Exception as e:
            if step_name in {"ema", VOLUME_STEP_NAME, ATR_STEP_NAME}:
                error_message = type(e).__name__
                logger.error("step %s failed: %s", step_name, error_message)
            else:
                error_message = str(e)
                logger.error(f"step {step_name} failed: {e}", exc_info=True)

            # 단계 실패 기록 (별도 트랜잭션)
            self._fail_step_checkpoint(step_name, error_message)

            raise

    def _is_step_completed(self, step_name: str) -> bool:
        """단계 완료 여부 확인"""
        if not self.job_id:
            return False

        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                if step_name == VOLUME_STEP_NAME:
                    context.job_id = self.job_id
                    return completed_volume_outcome(context, settings=get_settings()) is not None
                if step_name == ATR_STEP_NAME:
                    context.job_id = self.job_id
                    return completed_atr_outcome(context, settings=get_settings()) is not None
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
        if step_name == "ema" and self.job_id:
            with session_scope() as session:
                context = build_db_batch_context(session)
                checkpoint = context.checkpoint_repository.get_checkpoint(self.job_id, "ema")
                if checkpoint is not None and checkpoint.status == "completed":
                    return EmaBatchOutcome.completed(processed=checkpoint.items_processed)
        if step_name == VOLUME_STEP_NAME and self.job_id:
            with session_scope() as session:
                context = build_db_batch_context(session)
                context.job_id = self.job_id
                return completed_volume_outcome(context, settings=get_settings())
        if step_name == ATR_STEP_NAME and self.job_id:
            with session_scope() as session:
                context = build_db_batch_context(session)
                context.job_id = self.job_id
                return completed_atr_outcome(context, settings=get_settings())
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
        selection_metadata = None
        if isinstance(result, PriceSyncResult):
            items_processed = result.target_count
            items_failed = result.unsuccessful_count
            if items_failed:
                checkpoint_status = "completed_with_errors"
            selection_metadata = result.universe_selection_metadata
        elif isinstance(result, ValidationResult):
            items_processed = result.run.expected_symbols
            items_failed = result.run.error_count + result.run.critical_count
            if result.would_block or result.run.warning_count:
                checkpoint_status = "completed_with_errors"
        elif isinstance(result, KrxUniverseSyncResult):
            items_processed = result.member_count
            if result.status != "completed":
                items_failed = 1
                checkpoint_status = "completed_with_errors"
        elif isinstance(result, (EmaBatchOutcome, VolumeBatchOutcome, AtrBatchOutcome)):
            items_processed = result.processed
            items_failed = result.failed
            if result.has_errors:
                checkpoint_status = "completed_with_errors"
        elif isinstance(result, list):
            items_processed = len(result)
        elif isinstance(result, dict):
            items_processed = sum(len(v) if isinstance(v, list) else 1 for v in result.values())

        if step_name == "symbols" and self.universe_snapshot_status in {"partial", "failed"}:
            items_failed = max(items_failed, 1)
            checkpoint_status = "completed_with_errors"

        # 소요 시간 계산 (체크포인트에서 started_at 조회)
        duration_seconds = 0.0
        with session_scope() as session:
            context = build_db_batch_context(session)
            if context.checkpoint_repository:
                checkpoint = context.checkpoint_repository.get_checkpoint(self.job_id, step_name)
                if checkpoint and checkpoint.started_at:
                    duration_seconds = (datetime.utcnow() - checkpoint.started_at).total_seconds()

                metadata = {}
                if selection_metadata is not None:
                    metadata["universe_selection"] = selection_metadata
                if step_name == "symbols" and self.universe_snapshot_status is not None:
                    metadata["universe_snapshot_status"] = self.universe_snapshot_status
                    if self.universe_snapshot_id is not None:
                        metadata["universe_snapshot_id"] = self.universe_snapshot_id
                if isinstance(result, VolumeBatchOutcome):
                    metadata.update(json.loads(result.checkpoint_metadata(settings=get_settings())))
                elif isinstance(result, AtrBatchOutcome):
                    metadata.update(json.loads(result.checkpoint_metadata(settings=get_settings())))
                elif isinstance(result, EmaBatchOutcome):
                    metadata.update(json.loads(result.checkpoint_metadata()))

                context.checkpoint_repository.complete_step(
                    job_id=self.job_id,
                    step_name=step_name,
                    status=checkpoint_status,
                    items_processed=items_processed,
                    items_failed=items_failed,
                    step_metadata=json.dumps(metadata, sort_keys=True) if metadata else None,
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
                    status="completed_with_errors",
                    items_failed=1,
                    step_metadata=json.dumps({"outcome": "skipped", "reason": message}, sort_keys=True),
                )

    def _record_ema_outcome(self, outcome: EmaBatchOutcome) -> None:
        """Record an optional EMA skip against this crawl job only."""
        if not self.job_id:
            return
        with session_scope() as session:
            context = build_db_batch_context(session)
            context.job_id = self.job_id
            record_ema_checkpoint(context, outcome)

    def _record_volume_outcome(self, outcome: VolumeBatchOutcome) -> None:
        """Persist Volume skip/failure without altering the EMA checkpoint."""
        if not self.job_id:
            return
        with session_scope() as session:
            context = build_db_batch_context(session)
            context.job_id = self.job_id
            record_volume_checkpoint(context, outcome, settings=get_settings())

    def _record_atr_outcome(self, outcome: AtrBatchOutcome) -> None:
        """Persist ATR skip/failure without altering EMA or Volume checkpoints."""
        if not self.job_id:
            return
        with session_scope() as session:
            context = build_db_batch_context(session)
            context.job_id = self.job_id
            record_atr_checkpoint(context, outcome, settings=get_settings())

    def _execute_step(self, step_name: str, step_func: Callable[[BatchContext], Any]) -> Any:
        """단계 실행 (별도 트랜잭션)"""
        with session_scope() as session:
            context = build_db_batch_context(session)
            context.job_id = self.job_id
            if step_name in {"prices", "benchmarks", "krx_shadow"}:
                context.target_date = self.target_date or batch_target_date(get_settings())
            # Corporate-action refetches remain on the primary source.  Sam's
            # Kiwoom use is evidence-only and never a batch fallback.
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
                self.universe_snapshot_id = context.universe_snapshot_id
            if step_name == "krx_shadow":
                self.krx_universe_snapshot_status = context.krx_universe_snapshot_status
            return result

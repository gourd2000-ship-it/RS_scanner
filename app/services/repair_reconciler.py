"""Validate completed Sam results before they enter canonical price tables."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.metrics import increment_metric
from app.models.crawl_repair import CrawlRepairRequest, CrawlRepairResult
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.repositories.crawl_repair_repository import CrawlRepairRepository
from app.repositories.price_repository import PriceRepository
from app.schemas.market_data import DailyPricePayload
from app.services.repair_queue import (
    RepairResultRow,
    RepairValidationError,
    stable_result_hash,
)


@dataclass(frozen=True)
class RepairApplyOutcome:
    request_id: int
    application_status: str
    applied_row_count: int = 0
    conflict_dates: tuple[date, ...] = ()
    message: str | None = None


class RepairReconciler:
    """Apply only validated, non-conflicting Kiwoom rows to canonical prices.

    Sam never calls this service.  It runs with the autobot database session so
    a conflict or a malformed completed result cannot overwrite Naver data.
    """

    def __init__(self, session: Session, *, max_rows: int = 6000) -> None:
        self.session = session
        self.repository = CrawlRepairRepository(session)
        self.price_repository = PriceRepository(session)
        self.max_rows = max_rows

    def apply_completed(self, *, limit: int = 100) -> list[RepairApplyOutcome]:
        """Apply a bounded batch of completed, not-yet-applied requests."""
        return [
            self.apply_request(request.id)
            for request in self.repository.list_ready_for_application(limit=limit)
        ]

    def apply_request(self, request_id: int) -> RepairApplyOutcome:
        request = self.repository.get_for_application(request_id)
        if request is None:
            raise LookupError(f"repair request not found: {request_id}")
        if request.application_status == "applied":
            return RepairApplyOutcome(
                request_id=request.id,
                application_status="applied",
                applied_row_count=len(self.repository.list_results(request.id)),
            )
        if request.application_status in {"conflict", "rejected"}:
            return RepairApplyOutcome(
                request_id=request.id,
                application_status=request.application_status,
                message=request.application_error,
            )
        if request.status != "completed":
            raise ValueError(f"repair request is not completed: {request.status}")

        # Keep canonical writes and the application marker in one recoverable
        # savepoint.  The caller owns the outer transaction/commit.
        with self.session.begin_nested():
            return self._apply_completed_request(request)

    def _apply_completed_request(self, request: CrawlRepairRequest) -> RepairApplyOutcome:
        results = self.repository.list_results(request.id)
        try:
            self._validate_completed_results(request, results)
        except RepairValidationError as error:
            message = str(error)[:1000]
            self.repository.set_application_status(
                request_id=request.id,
                application_status="rejected",
                error_message=message,
            )
            increment_metric("repair_rejected_total")
            return RepairApplyOutcome(
                request_id=request.id,
                application_status="rejected",
                message=message,
            )

        existing = self._existing_prices(request.symbol, results)
        conflicts = [
            row.trade_date
            for row in results
            if row.trade_date in existing and self._values_differ(existing[row.trade_date], row)
        ]
        if conflicts:
            message = self._conflict_message(existing, results, conflicts)
            self.repository.set_application_status(
                request_id=request.id,
                application_status="conflict",
                error_message=message,
            )
            increment_metric("repair_conflict_total")
            return RepairApplyOutcome(
                request_id=request.id,
                application_status="conflict",
                conflict_dates=tuple(sorted(conflicts)),
                message=message,
            )

        missing_rows = [row for row in results if row.trade_date not in existing]
        if missing_rows:
            self.price_repository.save_symbol_prices(
                request.symbol,
                [self._to_price_payload(row) for row in missing_rows],
                crawl_job_id=request.job_id,
                provider="kiwoom",
                parser_version="sam/kiwoom-ohlc-query",
            )

        self._mark_target_result_applied(request, results)
        self.repository.set_application_status(
            request_id=request.id,
            application_status="applied",
        )
        increment_metric("repair_applied_total")
        return RepairApplyOutcome(
            request_id=request.id,
            application_status="applied",
            applied_row_count=len(missing_rows),
        )

    def _validate_completed_results(
        self,
        request: CrawlRepairRequest,
        results: list[CrawlRepairResult],
    ) -> None:
        if not results:
            raise RepairValidationError("completed repair request has no result rows")
        if len(results) > self.max_rows:
            raise RepairValidationError("repair result exceeds the row limit")

        attempt = self.repository.latest_attempt(request.id)
        if attempt is None or attempt.status != "completed":
            raise RepairValidationError("completed repair request has no completed attempt")
        if attempt.row_count != len(results):
            raise RepairValidationError("attempt row_count does not match result rows")
        if not attempt.data_complete:
            raise RepairValidationError("incomplete results cannot be applied")

        seen_dates: set[date] = set()
        for result in results:
            if result.symbol != request.symbol:
                raise RepairValidationError("result symbol does not match the repair request")
            if result.adjusted_price != request.adjusted_price:
                raise RepairValidationError("result adjusted_price does not match the request")
            if result.source not in {"kiwoom", "kiwoom_rest"}:
                raise RepairValidationError("result source is not an allowed Kiwoom source")
            if result.trade_date < (request.history_from or result.trade_date):
                raise RepairValidationError("result date is before the requested range")
            if result.trade_date > request.trade_date:
                raise RepairValidationError("result date is after the requested trade date")
            if result.trade_date in seen_dates:
                raise RepairValidationError("duplicate result trade date")
            seen_dates.add(result.trade_date)
            if result.change_rate is None:
                raise RepairValidationError("change_rate is required before canonical apply")
            self._validate_ohlcv(result)

        expected_latest = max(result.trade_date for result in results)
        if attempt.latest_date != expected_latest:
            raise RepairValidationError("attempt latest_date does not match result rows")

        typed_rows = [self._as_repair_row(result) for result in results]
        expected_hash = stable_result_hash(typed_rows)
        if attempt.result_hash and attempt.result_hash != expected_hash:
            raise RepairValidationError("attempt result_hash does not match result rows")

    def _existing_prices(
        self,
        symbol: str,
        results: Iterable[CrawlRepairResult],
    ) -> dict[date, DailyPrice]:
        dates = [result.trade_date for result in results]
        return {
            row.trade_date: row
            for row in self.session.scalars(
                select(DailyPrice)
                .join(Symbol, Symbol.id == DailyPrice.symbol_id)
                .where(Symbol.code == symbol, DailyPrice.trade_date.in_(dates))
            ).all()
        }

    @staticmethod
    def _values_differ(canonical: DailyPrice, result: CrawlRepairResult) -> bool:
        for field in ("open", "high", "low", "close", "volume", "change_rate"):
            if getattr(canonical, field) != getattr(result, field):
                return True
        return False

    def _conflict_message(
        self,
        existing: dict[date, DailyPrice],
        results: list[CrawlRepairResult],
        conflict_dates: list[date],
    ) -> str:
        canonical_rows = [
            self._as_repair_row(existing[trade_date], source="naver")
            for trade_date in sorted(conflict_dates)
        ]
        repair_rows = [
            self._as_repair_row(result)
            for result in results
            if result.trade_date in conflict_dates
        ]
        canonical_hash = stable_result_hash(canonical_rows)
        repair_hash = stable_result_hash(repair_rows)
        dates = ",".join(item.isoformat() for item in sorted(conflict_dates))
        return (
            f"provider_conflict dates={dates} "
            f"canonical_fingerprint={canonical_hash} "
            f"repair_fingerprint={repair_hash}"
        )[:1000]

    def _mark_target_result_applied(
        self,
        request: CrawlRepairRequest,
        results: list[CrawlRepairResult],
    ) -> None:
        target = None
        if request.crawl_target_result_id is not None:
            target = self.session.get(CrawlTargetResult, request.crawl_target_result_id)
        if target is None and request.job_id is not None:
            target = self.session.scalar(
                select(CrawlTargetResult).where(
                    CrawlTargetResult.job_id == request.job_id,
                    CrawlTargetResult.step_name == "prices",
                    CrawlTargetResult.target_key == request.symbol,
                )
            )
        if target is None:
            return

        now = datetime.utcnow()
        target.status = "fetched"
        target.provider = "kiwoom"
        target.rows_received = len(results)
        target.rows_persisted = len(results)
        target.latest_date_after = max(result.trade_date for result in results)
        target.trade_date = request.trade_date
        target.http_status = None
        target.error_class = None
        target.error_message = None
        target.updated_at = now

    @staticmethod
    def _to_price_payload(result: CrawlRepairResult) -> DailyPricePayload:
        return DailyPricePayload(
            trade_date=result.trade_date,
            open=result.open,
            high=result.high,
            low=result.low,
            close=result.close,
            volume=result.volume,
            change_rate=result.change_rate,
        )

    @staticmethod
    def _as_repair_row(
        row: CrawlRepairResult | DailyPrice,
        *,
        source: str | None = None,
    ) -> RepairResultRow:
        return RepairResultRow(
            symbol=getattr(row, "symbol", "canonical"),
            trade_date=row.trade_date,
            source=source or row.source,
            adjusted_price=getattr(row, "adjusted_price", True),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            change_rate=row.change_rate,
        )

    @staticmethod
    def _validate_ohlcv(row: CrawlRepairResult) -> None:
        try:
            if any(value <= 0 for value in (row.open, row.high, row.low, row.close)):
                raise RepairValidationError("OHLC values must be positive")
            if row.high < row.low or row.high < row.open or row.high < row.close:
                raise RepairValidationError("high is inconsistent with OHLC values")
            if row.low > row.open or row.low > row.close:
                raise RepairValidationError("low is inconsistent with OHLC values")
            if row.volume < 0:
                raise RepairValidationError("volume must not be negative")
        except (TypeError, InvalidOperation) as exc:
            raise RepairValidationError("OHLC values are not numeric") from exc

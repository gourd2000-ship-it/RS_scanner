"""Business rules for the Sam repair queue."""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.orm import Session

from app.core.metrics import increment_metric
from app.models.crawl_repair import CrawlRepairRequest
from app.repositories.crawl_repair_repository import (
    CrawlRepairRepository,
    RepairClaim,
)


class RepairValidationError(ValueError):
    """A submitted repair task or result violates the fixed contract."""


class RepairClaimError(ValueError):
    """A claim token or request state cannot be used for a mutation."""


@dataclass(frozen=True)
class RepairResultRow:
    symbol: str
    trade_date: date
    source: str
    adjusted_price: bool
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    change_rate: Decimal | None = None

    def as_persisted_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date,
            "source": self.source,
            "adjusted_price": self.adjusted_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "change_rate": self.change_rate,
        }


def classify_repair_error(
    *,
    status: str,
    error_class: str | None,
    error_message: str | None,
) -> str | None:
    """Map a Naver target result to a repair queue reason code."""
    if status not in {"failed", "partial"}:
        return None
    text = f"{error_class or ''} {error_message or ''}".lower()
    if "corporate" in text:
        return "corporate_action_unresolved"
    if "empty" in text or "no data" in text or "no rows" in text:
        return "empty_response"
    return "partial" if status == "partial" else "failed"


def stable_result_hash(rows: Iterable[RepairResultRow]) -> str:
    def canonical_number(value: object) -> str | None:
        if value is None:
            return None
        try:
            normalized = Decimal(str(value)).normalize()
            return format(normalized, "f")
        except (InvalidOperation, ValueError):
            return str(value)

    material = []
    for row in sorted(rows, key=lambda item: (item.symbol, item.trade_date)):
        material.append(
            {
                "symbol": row.symbol,
                "trade_date": row.trade_date.isoformat(),
                "source": row.source,
                "adjusted_price": row.adjusted_price,
                "open": canonical_number(row.open),
                "high": canonical_number(row.high),
                "low": canonical_number(row.low),
                "close": canonical_number(row.close),
                "volume": row.volume,
                "change_rate": canonical_number(row.change_rate),
            }
        )
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def sanitize_repair_error(message: str) -> str:
    value = str(message or "repair task failed").strip()
    value = re.sub(r"(?i)(authorization|token|password|secret|api[_-]?key)=\S+", r"\1=<redacted>", value)
    value = re.sub(r"https?://\S+", "<url>", value)
    return value[:1000]


def sanitize_repair_details(details: dict | None) -> dict:
    """Keep audit metadata bounded and prevent raw secrets/responses in JSON."""
    if not isinstance(details, dict):
        return {}
    blocked = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key|account)")

    def clean(value: object, *, depth: int = 0) -> object:
        if depth > 2:
            return "<truncated>"
        if isinstance(value, dict):
            return {
                str(key)[:80]: clean(item, depth=depth + 1)
                for key, item in list(value.items())[:20]
                if not blocked.search(str(key))
            }
        if isinstance(value, list):
            return [clean(item, depth=depth + 1) for item in value[:20]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value if not isinstance(value, str) else value[:500]
        return str(value)[:500]

    sanitized = clean(details)
    return sanitized if isinstance(sanitized, dict) else {}


class RepairQueueService:
    """Coordinates validation and repository state transitions."""

    def __init__(self, session: Session, *, max_rows: int = 6000) -> None:
        self.session = session
        self.repository = CrawlRepairRepository(session)
        self.max_rows = max_rows

    def enqueue_from_target(
        self,
        *,
        job_id: int | None,
        crawl_target_result_id: int | None,
        symbol: str,
        trade_date: date,
        error_type: str,
        history_from: date | None = None,
        adjusted_price: bool = True,
        max_attempts: int = 3,
    ) -> tuple[CrawlRepairRequest, bool]:
        request, created = self.repository.enqueue(
            job_id=job_id,
            crawl_target_result_id=crawl_target_result_id,
            symbol=symbol,
            trade_date=trade_date,
            error_type=error_type,
            history_from=history_from,
            adjusted_price=adjusted_price,
            max_attempts=max_attempts,
        )
        increment_metric("repair_requests_created" if created else "repair_requests_deduplicated")
        return request, created

    def claim(self, *, claimed_by: str, lease_seconds: int) -> RepairClaim | None:
        claim = self.repository.claim_one(
            claimed_by=claimed_by,
            lease_seconds=lease_seconds,
        )
        if claim is not None:
            increment_metric("repair_processing_total")
        return claim

    def complete(
        self,
        *,
        request_id: int,
        claim_token: str,
        claim_version: int | None,
        operation: str,
        symbol: str,
        from_date: date,
        to_date: date,
        adjusted_price: bool,
        executor: str,
        tool: str,
        mode: str,
        latest_date: date,
        row_count: int,
        data_complete: bool,
        rows: Iterable[RepairResultRow],
        result_hash: str | None = None,
        details: dict | None = None,
    ) -> CrawlRepairRequest:
        request = self.repository.get(request_id)
        if request is None:
            raise LookupError(f"repair request not found: {request_id}")
        if request.status != "processing":
            raise RepairClaimError(f"repair request is not processing: {request.status}")
        if operation != request.operation or operation != "daily_chart":
            raise RepairValidationError("operation does not match the repair request")
        if symbol != request.symbol:
            raise RepairValidationError("result symbol does not match the repair request")
        if to_date != request.trade_date or from_date != (request.history_from or from_date):
            raise RepairValidationError("result date range does not match the repair request")
        if adjusted_price != request.adjusted_price:
            raise RepairValidationError("adjusted_price does not match the repair request")
        if executor != "sam" or tool != "kiwoomcli":
            raise RepairValidationError("only the Sam kiwoomcli executor is allowed")
        if mode not in {"demo", "real"}:
            raise RepairValidationError("unsupported Kiwoom execution mode")
        if not data_complete:
            raise RepairValidationError("incomplete results must be submitted as a failure")

        materialized = list(rows)
        if not materialized:
            raise RepairValidationError("successful repair results must contain rows")
        if len(materialized) != row_count:
            raise RepairValidationError("row_count does not match submitted rows")
        if len(materialized) > self.max_rows:
            raise RepairValidationError("repair result exceeds the row limit")

        seen_dates: set[date] = set()
        for row in materialized:
            if row.symbol != symbol:
                raise RepairValidationError("result contains a different symbol")
            if row.adjusted_price != adjusted_price:
                raise RepairValidationError("result row adjusted_price mismatch")
            if row.source not in {"kiwoom", "kiwoom_rest"}:
                raise RepairValidationError("result source is not an allowed Kiwoom source")
            if row.trade_date < from_date or row.trade_date > to_date:
                raise RepairValidationError("result date is outside the requested range")
            if row.trade_date in seen_dates:
                raise RepairValidationError("duplicate result trade date")
            seen_dates.add(row.trade_date)
            self._validate_ohlcv(row)

        expected_latest = max(row.trade_date for row in materialized)
        if latest_date != expected_latest:
            raise RepairValidationError("latest_date does not match result rows")

        computed_hash = stable_result_hash(materialized)
        if result_hash is not None and result_hash != computed_hash:
            raise RepairValidationError("result_hash does not match result rows")

        try:
            completed = self.repository.complete(
                request_id=request_id,
                claim_token=claim_token,
                claim_version=claim_version,
                rows=(row.as_persisted_dict() for row in materialized),
                executor=executor,
                tool=tool,
                mode=mode,
                latest_date=latest_date,
                data_complete=data_complete,
                result_hash=computed_hash,
                details=sanitize_repair_details(details),
            )
        except (PermissionError, ValueError) as error:
            raise RepairClaimError(str(error)) from error
        increment_metric("repair_completed_total")
        return completed

    def fail(
        self,
        *,
        request_id: int,
        claim_token: str,
        claim_version: int | None,
        error_code: str,
        error_message: str,
        retryable: bool,
        http_status: int | None = None,
        retry_after_seconds: int = 0,
        details: dict | None = None,
    ) -> CrawlRepairRequest:
        if not error_code.strip():
            raise RepairValidationError("error_code must not be empty")
        if http_status is not None and not 100 <= http_status <= 599:
            raise RepairValidationError("http_status is invalid")
        try:
            request = self.repository.fail(
                request_id=request_id,
                claim_token=claim_token,
                claim_version=claim_version,
                error_code=error_code.strip()[:80],
                error_message=sanitize_repair_error(error_message),
                retryable=retryable,
                http_status=http_status,
                retry_after_seconds=max(0, min(retry_after_seconds, 86400)),
                details=sanitize_repair_details(details),
            )
        except (PermissionError, ValueError) as error:
            raise RepairClaimError(str(error)) from error
        increment_metric("repair_failed_total")
        if request.status == "pending":
            increment_metric("repair_retry_scheduled_total")
        return request

    def _validate_ohlcv(self, row: RepairResultRow) -> None:
        try:
            values = (row.open, row.high, row.low, row.close)
            if any(value <= 0 for value in values):
                raise RepairValidationError("OHLC values must be positive")
            if row.high < row.low or row.high < row.open or row.high < row.close:
                raise RepairValidationError("high is inconsistent with OHLC values")
            if row.low > row.open or row.low > row.close:
                raise RepairValidationError("low is inconsistent with OHLC values")
            if row.volume < 0:
                raise RepairValidationError("volume must not be negative")
        except (TypeError, InvalidOperation) as exc:
            raise RepairValidationError("OHLC values are not numeric") from exc

"""Bounded, page-at-a-time Kiwoom ``ka10081`` history collection for BT05."""

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
import re
from typing import Callable, Iterator, Protocol

from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.kiwoom_client import KiwoomChartResponse, KiwoomRestClient
from app.crawler.parsers.fchart import ParsedPriceRows
from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices
from app.schemas.market_data import DailyPricePayload


class FetchPage(Protocol):
    def __call__(
        self, code: str, *, base_date: str, continuation: bool, next_key: str | None
    ) -> KiwoomChartResponse: ...


class ParsePage(Protocol):
    def __call__(self, payload: object, *, response_bytes: int | None = None) -> ParsedPriceRows: ...


@dataclass(frozen=True)
class KiwoomHistoryRequest:
    code: str
    start: date
    end: date
    base_date: str
    market: str
    adjustment_type: str
    request_budget: int
    preparation_start: date | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("code is required")
        if self.end < self.start:
            raise ValueError("end must not be earlier than start")
        if self.preparation_start is not None and self.preparation_start > self.start:
            raise ValueError("preparation_start must not be later than start")
        if not re.fullmatch(r"[0-9]{8}", self.base_date) or self.base_date == "00000000":
            raise ValueError("base_date must be a fixed YYYYMMDD value")
        if not self.market.strip() or not self.adjustment_type.strip():
            raise ValueError("market and adjustment_type are required")
        if self.request_budget < 1:
            raise ValueError("request_budget must be at least one")

    @property
    def collection_start(self) -> date:
        return self.preparation_start or self.start


@dataclass(frozen=True)
class KiwoomHistoryPage:
    page_number: int
    rows: tuple[DailyPricePayload, ...]
    received_row_count: int
    invalid_row_count: int
    response_bytes: int | None
    retry_count: int
    duplicate_date_count: int
    source_payload_hash: str


@dataclass
class KiwoomHistorySummary:
    request: KiwoomHistoryRequest
    terminal_reason: str | None = None
    request_count: int = 0
    received_row_count: int = 0
    emitted_row_count: int = 0
    requested_row_count: int = 0
    preparation_row_count: int = 0
    invalid_row_count: int = 0
    invalid_row_reasons: dict[str, int] = field(default_factory=dict)
    duplicate_date_count: int = 0
    response_bytes: int = 0
    retry_count: int = 0
    error: dict[str, int | str | None] | None = None


@dataclass
class KiwoomHistoryIterator:
    request: KiwoomHistoryRequest
    fetch_page: FetchPage
    parse_page: ParsePage
    summary: KiwoomHistorySummary = field(init=False)

    def __post_init__(self) -> None:
        self.summary = KiwoomHistorySummary(request=self.request)

    def __iter__(self) -> Iterator[KiwoomHistoryPage]:
        continuation = False
        next_key: str | None = None
        seen_dates: set[date] = set()
        seen_continuation_keys: set[str] = set()

        while self.summary.request_count < self.request.request_budget:
            try:
                response = self.fetch_page(
                    self.request.code,
                    base_date=self.request.base_date,
                    continuation=continuation,
                    next_key=next_key,
                )
            except PriceFetchError as exc:
                self.summary.terminal_reason = "fetch_failed"
                self.summary.error = {
                    "class": type(exc).__name__,
                    "http_status": exc.http_status,
                    "retry_count": exc.retry_count,
                }
                return
            self.summary.request_count += 1
            self.summary.response_bytes += response.response_bytes
            self.summary.retry_count += response.retry_count
            try:
                parsed = self.parse_page(response.payload, response_bytes=response.response_bytes)
            except PriceParseError as exc:
                self.summary.invalid_row_count += exc.invalid_rows
                _add_count(self.summary.invalid_row_reasons, "parser_no_valid_rows", exc.invalid_rows)
                self.summary.terminal_reason = "provider_unsupported"
                self.summary.error = {"class": type(exc).__name__, "http_status": None, "retry_count": 0}
                return

            received = list(parsed)
            self.summary.received_row_count += len(received)
            invalid_rows = getattr(parsed, "invalid_rows", 0)
            self.summary.invalid_row_count += invalid_rows
            _add_count(self.summary.invalid_row_reasons, "parser_invalid_row", invalid_rows)
            if not received:
                self.summary.terminal_reason = "pagination_anomaly"
                return
            page_duplicates = 0
            rows: list[DailyPricePayload] = []
            for row in received:
                if row.trade_date in seen_dates:
                    page_duplicates += 1
                    continue
                seen_dates.add(row.trade_date)
                if self.request.collection_start <= row.trade_date <= self.request.end:
                    rows.append(row)
                    if row.trade_date < self.request.start:
                        self.summary.preparation_row_count += 1
                    else:
                        self.summary.requested_row_count += 1
            rows.sort(key=lambda row: row.trade_date)
            self.summary.duplicate_date_count += page_duplicates
            self.summary.emitted_row_count += len(rows)

            if received and page_duplicates == len(received):
                self.summary.terminal_reason = "pagination_anomaly"
                return
            yield KiwoomHistoryPage(
                page_number=self.summary.request_count,
                rows=tuple(rows),
                received_row_count=len(received),
                invalid_row_count=getattr(parsed, "invalid_rows", 0),
                response_bytes=response.response_bytes,
                retry_count=response.retry_count,
                duplicate_date_count=page_duplicates,
                source_payload_hash=_payload_hash(response.payload),
            )

            oldest = min((row.trade_date for row in received), default=None)
            if oldest is not None and oldest <= self.request.collection_start:
                self.summary.terminal_reason = "collection_start_reached"
                return
            if not response.continuation or not response.next_key:
                self.summary.terminal_reason = "provider_exhausted"
                return
            if response.next_key in seen_continuation_keys:
                self.summary.terminal_reason = "pagination_anomaly"
                return
            seen_continuation_keys.add(response.next_key)
            continuation = True
            next_key = response.next_key

        self.summary.terminal_reason = "request_budget_exhausted"


def iter_kiwoom_history(
    request: KiwoomHistoryRequest,
    *,
    client: KiwoomRestClient | None = None,
    fetch_page: FetchPage | None = None,
    parse_page: ParsePage = parse_kiwoom_daily_prices,
) -> KiwoomHistoryIterator:
    """Return a stateful iterator; consumers commit each yielded page before requesting more."""
    if fetch_page is None:
        client = client or KiwoomRestClient()
        configured_adjustment = str(getattr(client.settings, "kiwoom_adjusted_price_type", "")).strip()
        if configured_adjustment != request.adjustment_type:
            raise ValueError("request adjustment_type must match the bound Kiwoom client policy")
        fetch_page = client.fetch_daily_chart_page
    return KiwoomHistoryIterator(request=request, fetch_page=fetch_page, parse_page=parse_page)


def _add_count(values: dict[str, int], key: str, amount: int) -> None:
    if amount:
        values[key] = values.get(key, 0) + amount


def _payload_hash(payload: object) -> str:
    """Stable source-response lineage without retaining a full history page in memory."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(encoded).hexdigest()

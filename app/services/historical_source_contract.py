"""Read-only probes that establish historical price-source coverage."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable

from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.kiwoom_client import KiwoomChartResponse
from app.schemas.market_data import DailyPricePayload


ChartPageFetcher = Callable[..., KiwoomChartResponse]
ChartPageParser = Callable[[dict[str, Any]], Iterable[DailyPricePayload]]


DEFAULT_PROBE_SAMPLES: tuple[tuple[str, str], ...] = (
    ("005930", "current_corporate_action"),
    ("000660", "current_long_history"),
    ("035420", "current_large_cap"),
    ("068270", "market_transfer_kosdaq_to_kospi"),
    ("230980", "stored_delisted_kosdaq"),
    ("032980", "stored_delisted_kosdaq"),
)


@dataclass(frozen=True)
class HistoricalProbeRequest:
    """One bounded, reproducible read-only Kiwoom history probe."""

    code: str
    label: str
    base_date: str
    target_date: date
    max_pages: int = 8

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("code is required")
        if self.max_pages < 1:
            raise ValueError("max_pages must be at least one")
        if self.base_date == "00000000":
            raise ValueError("base_date must be a fixed YYYYMMDD date, not 00000000")
        try:
            parsed_base_date = datetime.strptime(self.base_date, "%Y%m%d").date()
        except ValueError as exc:
            raise ValueError("base_date must be a fixed YYYYMMDD date") from exc
        if self.target_date > parsed_base_date:
            raise ValueError("target_date cannot be after base_date")


@dataclass(frozen=True)
class HistoricalProbeResult:
    """A compact result safe to store in a source-contract report."""

    request: HistoricalProbeRequest
    page_count: int
    row_count: int
    unique_row_count: int
    duplicate_dates: tuple[date, ...]
    date_range: tuple[date, date] | None
    target_reached: bool
    terminal_reason: str
    response_bytes: int
    invalid_rows: int
    retry_count: int
    error: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.request.code,
            "label": self.request.label,
            "base_date": self.request.base_date,
            "target_date": self.request.target_date.isoformat(),
            "max_pages": self.request.max_pages,
            "page_count": self.page_count,
            "row_count": self.row_count,
            "unique_row_count": self.unique_row_count,
            "duplicate_dates": [value.isoformat() for value in self.duplicate_dates],
            "date_range": (
                {"first": self.date_range[0].isoformat(), "last": self.date_range[1].isoformat()}
                if self.date_range
                else None
            ),
            "target_reached": self.target_reached,
            "terminal_reason": self.terminal_reason,
            "response_bytes": self.response_bytes,
            "invalid_rows": self.invalid_rows,
            "retry_count": self.retry_count,
            "error": self.error,
        }


def default_probe_requests(
    *,
    base_date: str,
    target_date: date,
    max_pages: int,
) -> tuple[HistoricalProbeRequest, ...]:
    """Return the fixed, documented sample set for the BT01 source probe.

    The two ``stored_delisted`` codes are candidates selected from the local
    historical symbol record.  A successful response does not prove delisting;
    KRX/KIND evidence remains the authority for lifecycle events.
    """

    return tuple(
        HistoricalProbeRequest(
            code=code,
            label=label,
            base_date=base_date,
            target_date=target_date,
            max_pages=max_pages,
        )
        for code, label in DEFAULT_PROBE_SAMPLES
    )


def probe_kiwoom_daily_history(
    request: HistoricalProbeRequest,
    *,
    fetch_page: ChartPageFetcher,
    parse_page: ChartPageParser,
) -> HistoricalProbeResult:
    """Probe pages without persisting prices or retaining provider payloads.

    A fixed ``base_date`` is deliberately sent on every continuation request.
    This makes the observed adjusted-price contract reproducible and exposes
    overlapping dates at page boundaries instead of silently hiding them.
    """

    continuation = False
    next_key: str | None = None
    dates: list[date] = []
    duplicate_dates: set[date] = set()
    seen_dates: set[date] = set()
    page_count = 0
    row_count = 0
    response_bytes = 0
    invalid_rows = 0
    retry_count = 0

    for _ in range(request.max_pages):
        try:
            response = fetch_page(
                request.code,
                base_date=request.base_date,
                continuation=continuation,
                next_key=next_key,
            )
        except PriceFetchError as exc:
            return _result(
                request,
                page_count=page_count,
                row_count=row_count,
                dates=dates,
                duplicate_dates=duplicate_dates,
                response_bytes=response_bytes,
                invalid_rows=invalid_rows,
                retry_count=retry_count,
                terminal_reason="fetch_failed",
                error=_safe_error(exc),
            )

        page_count += 1
        response_bytes += response.response_bytes
        retry_count += response.retry_count
        try:
            parsed_page = parse_page(response.payload)
            parsed_rows = list(parsed_page)
        except PriceParseError as exc:
            invalid_rows += exc.invalid_rows
            return _result(
                request,
                page_count=page_count,
                row_count=row_count,
                dates=dates,
                duplicate_dates=duplicate_dates,
                response_bytes=response_bytes,
                invalid_rows=invalid_rows,
                retry_count=retry_count,
                terminal_reason="parse_failed",
                error=_safe_error(exc),
            )
        row_count += len(parsed_rows)
        invalid_rows += int(getattr(parsed_page, "invalid_rows", 0))
        for row in parsed_rows:
            if row.trade_date in seen_dates:
                duplicate_dates.add(row.trade_date)
            else:
                seen_dates.add(row.trade_date)
                dates.append(row.trade_date)

        if dates and min(dates) <= request.target_date:
            return _result(
                request,
                page_count=page_count,
                row_count=row_count,
                dates=dates,
                duplicate_dates=duplicate_dates,
                response_bytes=response_bytes,
                invalid_rows=invalid_rows,
                retry_count=retry_count,
                terminal_reason="target_reached",
            )
        if not response.continuation or not response.next_key:
            return _result(
                request,
                page_count=page_count,
                row_count=row_count,
                dates=dates,
                duplicate_dates=duplicate_dates,
                response_bytes=response_bytes,
                invalid_rows=invalid_rows,
                retry_count=retry_count,
                terminal_reason="completed",
            )
        continuation = True
        next_key = response.next_key

    return _result(
        request,
        page_count=page_count,
        row_count=row_count,
        dates=dates,
        duplicate_dates=duplicate_dates,
        response_bytes=response_bytes,
        invalid_rows=invalid_rows,
        retry_count=retry_count,
        terminal_reason="page_limit_reached",
    )


def _result(
    request: HistoricalProbeRequest,
    *,
    page_count: int,
    row_count: int,
    dates: list[date],
    duplicate_dates: set[date],
    response_bytes: int,
    invalid_rows: int,
    retry_count: int,
    terminal_reason: str,
    error: dict[str, object] | None = None,
) -> HistoricalProbeResult:
    unique_dates = sorted(set(dates))
    date_range = (unique_dates[0], unique_dates[-1]) if unique_dates else None
    return HistoricalProbeResult(
        request=request,
        page_count=page_count,
        row_count=row_count,
        unique_row_count=len(unique_dates),
        duplicate_dates=tuple(sorted(duplicate_dates)),
        date_range=date_range,
        target_reached=bool(date_range and date_range[0] <= request.target_date),
        terminal_reason=terminal_reason,
        response_bytes=response_bytes,
        invalid_rows=invalid_rows,
        retry_count=retry_count,
        error=error,
    )


def _safe_error(exc: PriceFetchError | PriceParseError) -> dict[str, object]:
    error: dict[str, object] = {"class": type(exc).__name__}
    if isinstance(exc, PriceFetchError) and exc.http_status is not None:
        error["http_status"] = exc.http_status
    if isinstance(exc, PriceParseError):
        error["invalid_rows"] = exc.invalid_rows
    return error

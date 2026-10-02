"""BT05 bounded Kiwoom history iterator contracts."""

from datetime import date
from decimal import Decimal

from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.kiwoom_client import KiwoomChartResponse
from app.crawler.sources.kiwoom_history import KiwoomHistoryRequest, iter_kiwoom_history
from app.schemas.market_data import DailyPricePayload


def _row(day: str) -> DailyPricePayload:
    return DailyPricePayload(
        trade_date=date.fromisoformat(day), open=Decimal("100"), high=Decimal("101"),
        low=Decimal("99"), close=Decimal("100"), volume=100, change_rate=Decimal("0"),
    )


def _response(*, continuation: bool, next_key: str | None) -> KiwoomChartResponse:
    return KiwoomChartResponse(
        payload={}, response_bytes=100, status_code=200, continuation=continuation, next_key=next_key
    )


def test_iterator_yields_bounded_pages_with_preparation_history_and_stops_at_collection_start():
    calls: list[tuple[str, str, bool, str | None]] = []
    responses = [
        _response(continuation=True, next_key="older"),
        _response(continuation=True, next_key="oldest"),
    ]
    parsed = [
        [_row("2026-01-03"), _row("2026-01-02")],
        [_row("2025-01-05"), _row("2025-01-04"), _row("2025-01-03")],
    ]

    def fetch_page(code, *, base_date, continuation, next_key):
        calls.append((code, base_date, continuation, next_key))
        return responses.pop(0)

    iterator = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="005930", start=date(2025, 1, 5), end=date(2026, 1, 2),
            preparation_start=date(2025, 1, 3), base_date="20260103", market="KOSPI",
            adjustment_type="1", request_budget=3,
        ),
        fetch_page=fetch_page,
        parse_page=lambda _payload, **_kwargs: parsed.pop(0),
    )

    pages = list(iterator)

    assert [[row.trade_date for row in page.rows] for page in pages] == [
        [date(2026, 1, 2)],
        [date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5)],
    ]
    assert calls == [
        ("005930", "20260103", False, None),
        ("005930", "20260103", True, "older"),
    ]
    assert iterator.summary.terminal_reason == "collection_start_reached"
    assert iterator.summary.request_count == 2
    assert iterator.summary.preparation_row_count == 2
    assert iterator.summary.requested_row_count == 2


def test_iterator_detects_repeated_continuation_pages_without_retaining_price_history():
    calls: list[str | None] = []
    responses = [
        _response(continuation=True, next_key="same"),
        _response(continuation=True, next_key="same"),
    ]
    parsed = [[_row("2026-01-03")], [_row("2026-01-03")]]

    def fetch_page(_code, *, base_date, continuation, next_key):
        calls.append(next_key)
        return responses.pop(0)

    iterator = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="005930", start=date(2020, 1, 1), end=date(2026, 1, 3),
            base_date="20260103", market="KOSPI", adjustment_type="1", request_budget=5,
        ),
        fetch_page=fetch_page,
        parse_page=lambda _payload, **_kwargs: parsed.pop(0),
    )

    pages = list(iterator)

    assert len(pages) == 1
    assert iterator.summary.terminal_reason == "pagination_anomaly"
    assert iterator.summary.duplicate_date_count == 1
    assert calls == [None, "same"]


def test_iterator_records_unsupported_parse_response_and_fetch_failure_instead_of_claiming_coverage():
    def parse_failure(*_args, **_kwargs):
        raise PriceParseError("no valid rows", invalid_rows=3, response_bytes=261)

    unsupported = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="230980", start=date(2020, 1, 1), end=date(2026, 1, 1),
            base_date="20260604", market="KOSDAQ", adjustment_type="1", request_budget=1,
        ),
        fetch_page=lambda *_args, **_kwargs: _response(continuation=False, next_key=None),
        parse_page=parse_failure,
    )
    assert list(unsupported) == []
    assert unsupported.summary.terminal_reason == "provider_unsupported"
    assert unsupported.summary.invalid_row_count == 3
    assert unsupported.summary.invalid_row_reasons == {"parser_no_valid_rows": 3}

    def fetch_failure(*_args, **_kwargs):
        raise PriceFetchError("timed out", url="kiwoom://chart", http_status=503, retry_count=2)

    failed = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="230980", start=date(2020, 1, 1), end=date(2026, 1, 1),
            base_date="20260604", market="KOSDAQ", adjustment_type="1", request_budget=1,
        ),
        fetch_page=fetch_failure,
        parse_page=lambda *_args, **_kwargs: [],
    )
    assert list(failed) == []
    assert failed.summary.terminal_reason == "fetch_failed"
    assert failed.summary.error == {"class": "PriceFetchError", "http_status": 503, "retry_count": 2}


def test_iterator_rejects_a_request_adjustment_policy_that_does_not_match_the_bound_client():
    class Client:
        settings = type("Settings", (), {"kiwoom_adjusted_price_type": "1"})()

        def fetch_daily_chart_page(self, *_args, **_kwargs):
            return _response(continuation=False, next_key=None)

    request = KiwoomHistoryRequest(
        code="005930", start=date(2020, 1, 1), end=date(2026, 1, 1),
        base_date="20260103", market="KOSPI", adjustment_type="0", request_budget=1,
    )

    try:
        iter_kiwoom_history(request, client=Client())
    except ValueError as exc:
        assert "adjustment_type" in str(exc)
    else:
        raise AssertionError("mismatched client adjustment policy was accepted")


def test_iterator_stops_when_request_budget_is_exhausted_before_target_history_is_reached():
    iterator = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="005930", start=date(2020, 1, 1), end=date(2026, 1, 3),
            base_date="20260103", market="KOSPI", adjustment_type="1", request_budget=1,
        ),
        fetch_page=lambda *_args, **_kwargs: _response(continuation=True, next_key="older"),
        parse_page=lambda *_args, **_kwargs: [_row("2026-01-03")],
    )

    assert len(list(iterator)) == 1
    assert iterator.summary.terminal_reason == "request_budget_exhausted"


def test_iterator_marks_an_empty_continuation_page_as_a_pagination_anomaly():
    iterator = iter_kiwoom_history(
        KiwoomHistoryRequest(
            code="005930", start=date(2020, 1, 1), end=date(2026, 1, 3),
            base_date="20260103", market="KOSPI", adjustment_type="1", request_budget=1,
        ),
        fetch_page=lambda *_args, **_kwargs: _response(continuation=True, next_key="older"),
        parse_page=lambda *_args, **_kwargs: [],
    )

    assert list(iterator) == []
    assert iterator.summary.terminal_reason == "pagination_anomaly"

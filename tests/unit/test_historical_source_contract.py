from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.kiwoom_client import KiwoomChartResponse
from app.schemas.market_data import DailyPricePayload
from app.services.historical_source_contract import (
    HistoricalProbeRequest,
    default_probe_requests,
    probe_kiwoom_daily_history,
)


def _row(day: str) -> DailyPricePayload:
    return DailyPricePayload(
        trade_date=date.fromisoformat(day),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        change_rate=Decimal("0"),
    )


def _response(*, continuation: bool, next_key: str | None) -> KiwoomChartResponse:
    return KiwoomChartResponse(
        payload={"rows": []},
        response_bytes=100,
        status_code=200,
        continuation=continuation,
        next_key=next_key,
    )


def test_probe_keeps_one_fixed_base_date_and_reports_duplicate_page_boundary():
    calls: list[tuple[str, str, bool, str | None]] = []
    responses = [
        (_response(continuation=True, next_key="next-1"), [_row("2026-09-04"), _row("2026-09-03")]),
        (_response(continuation=False, next_key=None), [_row("2026-09-03"), _row("2012-12-28")]),
    ]

    def fetch_page(code, *, base_date, continuation, next_key):
        calls.append((code, base_date, continuation, next_key))
        return responses.pop(0)[0]

    def parse_page(_payload):
        return responses[0][1] if responses else [_row("2026-09-03"), _row("2012-12-28")]

    # Keep parser output coupled to the response sequence without exposing API payloads.
    parsed_pages = [
        [_row("2026-09-04"), _row("2026-09-03")],
        [_row("2026-09-03"), _row("2012-12-28")],
    ]
    parse_index = 0

    def parse_sequenced(_payload):
        nonlocal parse_index
        parsed = parsed_pages[parse_index]
        parse_index += 1
        return parsed

    result = probe_kiwoom_daily_history(
        HistoricalProbeRequest(
            code="005930",
            label="current_corporate_action",
            base_date="20260904",
            target_date=date(2013, 1, 1),
            max_pages=3,
        ),
        fetch_page=fetch_page,
        parse_page=parse_sequenced,
    )

    assert calls == [
        ("005930", "20260904", False, None),
        ("005930", "20260904", True, "next-1"),
    ]
    assert result.page_count == 2
    assert result.unique_row_count == 3
    assert result.duplicate_dates == (date(2026, 9, 3),)
    assert result.date_range == (date(2012, 12, 28), date(2026, 9, 4))
    assert result.target_reached is True
    assert result.terminal_reason == "target_reached"


def test_probe_marks_page_limit_without_claiming_history_is_complete():
    def fetch_page(_code, *, base_date, continuation, next_key):
        assert base_date == "20260904"
        assert continuation is False
        assert next_key is None
        return _response(continuation=True, next_key="next-1")

    result = probe_kiwoom_daily_history(
        HistoricalProbeRequest(
            code="000660",
            label="current",
            base_date="20260904",
            target_date=date(2013, 1, 1),
            max_pages=1,
        ),
        fetch_page=fetch_page,
        parse_page=lambda _payload: [_row("2026-09-04")],
    )

    assert result.page_count == 1
    assert result.target_reached is False
    assert result.terminal_reason == "page_limit_reached"


def test_probe_counts_every_received_row_and_preserves_parser_invalid_count():
    class ParsedRows(list):
        invalid_rows = 2

    responses = [
        _response(continuation=True, next_key="next-1"),
        _response(continuation=True, next_key="next-2"),
        _response(continuation=False, next_key=None),
    ]

    def fetch_page(_code, *, base_date, continuation, next_key):
        return responses.pop(0)

    result = probe_kiwoom_daily_history(
        HistoricalProbeRequest(
            code="005930",
            label="duplicate_boundary",
            base_date="20260904",
            target_date=date(2013, 1, 1),
            max_pages=3,
        ),
        fetch_page=fetch_page,
        parse_page=lambda _payload: ParsedRows([_row("2026-09-04")]),
    )

    assert result.row_count == 3
    assert result.unique_row_count == 1
    assert result.duplicate_dates == (date(2026, 9, 4),)
    assert result.invalid_rows == 6


def test_probe_records_provider_failure_without_secret_or_payload():
    def fetch_page(_code, *, base_date, continuation, next_key):
        raise PriceFetchError(
            "provider unavailable",
            url="https://api.kiwoom.com/api/dostk/chart",
            http_status=503,
        )

    result = probe_kiwoom_daily_history(
        HistoricalProbeRequest(
            code="230980",
            label="stored_delisted",
            base_date="20260820",
            target_date=date(2013, 1, 1),
            max_pages=2,
        ),
        fetch_page=fetch_page,
        parse_page=lambda _payload: [],
    )

    assert result.page_count == 0
    assert result.terminal_reason == "fetch_failed"
    assert result.error == {"class": "PriceFetchError", "http_status": 503}


def test_probe_keeps_received_page_metadata_when_parsing_fails():
    def fetch_page(_code, *, base_date, continuation, next_key):
        return _response(continuation=False, next_key=None)

    def parse_page(_payload):
        raise PriceParseError("no valid rows", invalid_rows=2, response_bytes=100)

    result = probe_kiwoom_daily_history(
        HistoricalProbeRequest(
            code="230980",
            label="stored_delisted",
            base_date="20260820",
            target_date=date(2013, 1, 1),
            max_pages=2,
        ),
        fetch_page=fetch_page,
        parse_page=parse_page,
    )

    assert result.page_count == 1
    assert result.response_bytes == 100
    assert result.invalid_rows == 2
    assert result.terminal_reason == "parse_failed"


def test_probe_rejects_non_fixed_or_invalid_base_dates():
    with pytest.raises(ValueError, match="fixed YYYYMMDD"):
        HistoricalProbeRequest(
            code="005930",
            label="current",
            base_date="00000000",
            target_date=date(2013, 1, 1),
        )


def test_default_probe_requests_cover_current_corporate_action_delisting_and_market_transfer_samples():
    requests = default_probe_requests(
        base_date="20260904",
        target_date=date(2013, 1, 1),
        max_pages=8,
    )

    assert len(requests) == 6
    assert {request.label for request in requests} >= {
        "current_corporate_action",
        "stored_delisted_kosdaq",
        "market_transfer_kosdaq_to_kospi",
    }
    assert all(request.base_date == "20260904" for request in requests)
    assert all(request.target_date == date(2013, 1, 1) for request in requests)

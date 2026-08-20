"""Kiwoom REST API chart response parsers."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.exceptions import PriceParseError
from app.crawler.parsers.fchart import ParsedPriceRows
from app.schemas.market_data import DailyPricePayload


_ROWS_KEYS = (
    "stk_dt_pole_chart_qry",
    "ka10081OutBlock1",
    "daily_chart",
    "rows",
    "data",
    "output",
    "output1",
)


def _value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    raise KeyError(keys[0])


def _decimal(value: Any) -> Decimal:
    text = str(value).strip().replace(",", "")
    return Decimal(text)


def _trade_date(value: Any) -> date:
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("invalid Kiwoom trade date")
    return datetime.strptime(text, "%Y%m%d").date()


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in _ROWS_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            if rows:
                return rows
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested:
                return nested
    return []


def parse_kiwoom_daily_prices(
    payload: Any,
    *,
    response_bytes: int | None = None,
) -> ParsedPriceRows:
    """Normalize Kiwoom ``ka10081`` rows into the project price contract.

    Kiwoom numeric values may contain commas or an explicit sign.  The parser
    keeps negative values so the shared market-data validator can reject them
    instead of silently turning bad provider data into valid prices.
    """
    rows = _rows_from_payload(payload)
    if not rows:
        raise PriceParseError(
            "kiwoom daily chart has no data rows",
            response_bytes=response_bytes,
        )

    parsed: list[DailyPricePayload] = []
    invalid_rows = 0
    for row in rows:
        try:
            close = _decimal(_value(row, "cur_prc", "close", "close_pric"))
            parsed.append(
                DailyPricePayload(
                    trade_date=_trade_date(_value(row, "dt", "date", "trade_date")),
                    open=_decimal(_value(row, "open_pric", "open")),
                    high=_decimal(_value(row, "high_pric", "high")),
                    low=_decimal(_value(row, "low_pric", "low")),
                    close=close,
                    volume=int(_decimal(_value(row, "trde_qty", "volume"))),
                    change_rate=_decimal(
                        row.get("flu_rt", row.get("change_rate", row.get("prdy_ctrt", 0)))
                    ),
                )
            )
        except (ArithmeticError, KeyError, TypeError, ValueError):
            invalid_rows += 1

    if not parsed:
        raise PriceParseError(
            "kiwoom daily chart has no valid price rows",
            invalid_rows=invalid_rows,
            response_bytes=response_bytes,
        )

    return ParsedPriceRows(
        sorted(parsed, key=lambda row: row.trade_date),
        invalid_rows=invalid_rows,
        response_bytes=response_bytes,
    )

import json
import re
from datetime import date
from decimal import Decimal

from app.core.exceptions import PriceParseError
from app.schemas.market_data import DailyPricePayload


class ParsedPriceRows(list[DailyPricePayload]):
    """Parsed rows plus the number of discarded rows in the response."""

    def __init__(
        self,
        rows: list[DailyPricePayload] | None = None,
        *,
        invalid_rows: int = 0,
        response_bytes: int | None = None,
    ) -> None:
        super().__init__(rows or [])
        self.invalid_rows = invalid_rows
        self.response_bytes = response_bytes


def parse_fchart_prices(raw_text: str) -> ParsedPriceRows:
    """Naver fchart API 응답을 DailyPricePayload 리스트로 변환 (수정주가)."""
    text = raw_text.strip()
    response_bytes = len(raw_text.encode("utf-8"))
    if not text:
        raise PriceParseError("empty fchart response", response_bytes=response_bytes)

    # 비표준 JSON 처리: single-quote → double-quote, trailing comma 제거
    cleaned = text.replace("'", '"')
    cleaned = re.sub(r",\s*]", "]", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise PriceParseError("invalid fchart JSON", response_bytes=response_bytes) from exc

    if not isinstance(data, list) or len(data) < 2:
        raise PriceParseError("fchart response has no data rows", response_bytes=response_bytes)

    rows: list[DailyPricePayload] = []
    invalid_rows = 0
    for entry in data[1:]:
        try:
            if not isinstance(entry, list) or len(entry) < 6:
                raise ValueError("price row has fewer than six fields")

            date_str = str(entry[0]).strip().strip('"')
            if len(date_str) != 8 or not date_str.isdigit():
                raise ValueError("invalid trade date")

            trade_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            rows.append(DailyPricePayload(
                trade_date=trade_date,
                open=Decimal(str(entry[1])),
                high=Decimal(str(entry[2])),
                low=Decimal(str(entry[3])),
                close=Decimal(str(entry[4])),
                volume=int(entry[5]),
                change_rate=Decimal("0"),
            ))
        except (ArithmeticError, TypeError, ValueError):
            invalid_rows += 1

    if not rows:
        raise PriceParseError(
            "fchart response has no valid price rows",
            invalid_rows=invalid_rows,
            response_bytes=response_bytes,
        )

    return ParsedPriceRows(
        sorted(rows, key=lambda r: r.trade_date),
        invalid_rows=invalid_rows,
        response_bytes=response_bytes,
    )

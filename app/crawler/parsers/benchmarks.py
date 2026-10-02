import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from app.core.exceptions import PriceParseError
from app.schemas.market_data import BenchmarkPricePayload


def parse_benchmark_prices(html: str, *, market: str, benchmark_code: str) -> list[BenchmarkPricePayload]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table.type_1 tr"):
        cells = [td.get_text(strip=True).replace(",", "") for td in tr.select("td")]
        if len(cells) < 5 or not cells[0]:
            continue
        try:
            close = Decimal(cells[1])
            change_rate = Decimal(cells[3].replace("%", "").replace("+", "")) / 100 if len(cells) > 3 and cells[3] else Decimal("0")
            rows.append(
                BenchmarkPricePayload(
                    benchmark_code=benchmark_code,
                    market=market,
                    trade_date=parse_date(cells[0]).date(),
                    close=close,
                    change_rate=change_rate,
                    open=close,
                    high=close,
                    low=close,
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return rows


def parse_naver_index_prices(
    payload: str,
    *,
    market: str,
    benchmark_code: str,
    expected_naver_code: str,
) -> list[BenchmarkPricePayload]:
    """네이버 모바일 증권의 일별 지수 JSON 응답을 검증해 변환한다."""
    response_bytes = len(payload.encode("utf-8"))
    try:
        decoded = json.loads(payload, parse_float=Decimal)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PriceParseError(
            "Naver index response is not valid JSON",
            response_bytes=response_bytes,
        ) from exc

    if not isinstance(decoded, dict) or decoded.get("resultCode") != "success":
        raise PriceParseError(
            "Naver index response did not report success",
            response_bytes=response_bytes,
        )

    result = decoded.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("siseList"), list):
        raise PriceParseError(
            "Naver index response is missing result.siseList",
            response_bytes=response_bytes,
        )

    rows: list[BenchmarkPricePayload] = []
    for index, item in enumerate(result["siseList"]):
        try:
            if not isinstance(item, dict) or item.get("cd") != expected_naver_code:
                raise ValueError("unexpected index code")

            date_text = str(item["dt"])
            if re.fullmatch(r"\d{8}", date_text) is None:
                raise ValueError("invalid trade date")
            trade_date = datetime.strptime(date_text, "%Y%m%d").date()
            close = Decimal(str(item["ncv"]))
            change = Decimal(str(item["cv"]))
            change_rate = Decimal(str(item["cr"])) / Decimal("100")
            open_price = Decimal(str(item["ov"]))
            high = Decimal(str(item["hv"]))
            low = Decimal(str(item["lv"]))
            if not all(
                value.is_finite()
                for value in (close, change, change_rate, open_price, high, low)
            ):
                raise ValueError("non-finite index value")
            if min(close, open_price, high, low) <= 0:
                raise ValueError("non-positive index price")
            if high < max(open_price, close) or low > min(open_price, close) or high < low:
                raise ValueError("inconsistent index OHLC values")

            rows.append(
                BenchmarkPricePayload(
                    benchmark_code=benchmark_code,
                    market=market,
                    trade_date=trade_date,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=None,
                    change_rate=change_rate,
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise PriceParseError(
                f"Invalid Naver index row at position {index}",
                invalid_rows=1,
                response_bytes=response_bytes,
            ) from exc

    return rows

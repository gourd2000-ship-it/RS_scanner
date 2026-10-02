import json
import re

from bs4 import BeautifulSoup

from app.core.exceptions import PriceParseError
from app.schemas.market_data import SymbolPayload


def parse_etf_codes(json_text: str) -> set[str]:
    """Naver ETF JSON API 응답에서 ETF 종목 코드 set을 추출.

    API: https://finance.naver.com/api/sise/etfItemList.naver
    응답: {"resultCode":"SUCCESS","result":{"etfItemList":[{"itemcode":"069500",...}]}}
    """
    try:
        data = json.loads(json_text)
        return {item["itemcode"] for item in data["result"]["etfItemList"]}
    except (KeyError, TypeError, json.JSONDecodeError):
        return set()


def is_etn_name(name: str) -> bool:
    """한국 ETN 종목명 판별. ETN 종목명은 "...ETN", "...ETN(H)" 등으로 끝난다.

    코드 prefix(예: 59xxxx)는 실제 ETN 코드와 맞지 않아 신뢰할 수 없으므로 종목명을 사용한다.
    """
    return "ETN" in name.upper()


def parse_symbols(html: str, *, market: str) -> list[SymbolPayload]:
    soup = BeautifulSoup(html, "lxml")
    symbols: list[SymbolPayload] = []

    # Naver uses alphanumeric identifiers for ETF/ETN and some share classes
    # (for example ``0005D0`` and ``00088K``).  Restricting this to ``\d+``
    # silently truncated those identifiers and made the subsequent price URL
    # point at a different/non-existent instrument.
    for link in soup.select("a[href*='item/main.naver']"):
        href = link.get("href", "")
        match = re.search(r"(?:[?&])code=([0-9A-Za-z]+)", href)
        name = link.get_text(strip=True)
        if not match or not name:
            continue
        symbols.append(SymbolPayload(code=match.group(1), name=name, market=market))

    unique = {(row.code, row.market): row for row in symbols}
    return list(unique.values())


def parse_naver_individual_stock_page(
    payload: str,
    *,
    expected_index: int,
) -> tuple[list[SymbolPayload], int, bool]:
    """Parse the current Naver stock-list API page and its pagination contract."""
    try:
        decoded = json.loads(payload)
        total_count = int(decoded["totalCount"])
        response_index = int(decoded["index"])
        page_size = int(decoded["size"])
        has_next = decoded["hasNext"]
        items = decoded["items"]
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise PriceParseError("Naver individual-stock response has invalid pagination metadata") from exc
    if (
        not isinstance(decoded, dict)
        or response_index != expected_index
        or total_count < 0
        or page_size < 1
        or not isinstance(has_next, bool)
        or not isinstance(items, list)
        or len(items) > page_size
        or has_next != ((expected_index + 1) * page_size < total_count)
    ):
        raise PriceParseError("Naver individual-stock response has invalid pagination metadata")

    symbols: list[SymbolPayload] = []
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            raise PriceParseError(f"Invalid Naver individual-stock row at position {index}")
        code = row.get("itemCode")
        name = row.get("itemName")
        market = row.get("marketType")
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9A-Za-z]{6}", code) is None
            or not isinstance(name, str)
            or not name.strip()
            or market not in {"KOSPI", "KOSDAQ"}
        ):
            raise PriceParseError(f"Invalid Naver individual-stock row at position {index}")
        symbols.append(SymbolPayload(code=code, name=name.strip(), market=market))
    return symbols, total_count, has_next


def parse_naver_fund_symbols(
    payload: str,
    *,
    list_key: str,
    symbol_type: str,
) -> list[SymbolPayload]:
    """Parse Naver's full ETF or ETN list response."""
    if symbol_type not in {"etf", "etn"} or list_key not in {"etfItemList", "etnItemList"}:
        raise PriceParseError("Unsupported Naver fund-list contract")
    try:
        decoded = json.loads(payload)
        result = decoded["result"]
        items = result[list_key]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise PriceParseError("Naver fund-list response has invalid JSON structure") from exc
    result_code = decoded.get("resultCode") if isinstance(decoded, dict) else None
    if not isinstance(result_code, str) or result_code.lower() != "success":
        raise PriceParseError("Naver fund-list response did not report success")
    if not isinstance(items, list) or not items:
        raise PriceParseError("Naver fund-list response is empty or invalid")

    symbols: list[SymbolPayload] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PriceParseError(f"Invalid Naver fund row at position {index}")
        code = item.get("itemcode")
        name = item.get("itemname")
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9A-Za-z]{6}", code) is None
            or not isinstance(name, str)
            or not name.strip()
        ):
            raise PriceParseError(f"Invalid Naver fund row at position {index}")
        symbols.append(
            SymbolPayload(
                code=code,
                name=name.strip(),
                market="KOSPI",
                symbol_type=symbol_type,
            )
        )
    return symbols

import json
import re

from bs4 import BeautifulSoup

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

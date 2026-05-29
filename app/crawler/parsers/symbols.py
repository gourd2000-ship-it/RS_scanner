import re

from bs4 import BeautifulSoup

from app.schemas.market_data import SymbolPayload


def parse_symbols(html: str, *, market: str) -> list[SymbolPayload]:
    soup = BeautifulSoup(html, "lxml")
    symbols: list[SymbolPayload] = []

    for link in soup.select("a[href*='item/main.naver?code=']"):
        href = link.get("href", "")
        match = re.search(r"code=(\d+)", href)
        name = link.get_text(strip=True)
        if not match or not name:
            continue
        symbols.append(SymbolPayload(code=match.group(1), name=name, market=market))

    unique = {(row.code, row.market): row for row in symbols}
    return list(unique.values())

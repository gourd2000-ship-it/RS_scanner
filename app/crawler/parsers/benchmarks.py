from decimal import Decimal

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from app.schemas.market_data import BenchmarkPricePayload


def parse_benchmark_prices(html: str, *, market: str, benchmark_code: str) -> list[BenchmarkPricePayload]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table.type_1 tr"):
        cells = [td.get_text(strip=True).replace(",", "") for td in tr.select("td")]
        if len(cells) < 5 or not cells[0]:
            continue
        try:
            rows.append(
                BenchmarkPricePayload(
                    benchmark_code=benchmark_code,
                    market=market,
                    trade_date=parse_date(cells[0]).date(),
                    close=Decimal(cells[1]),
                    change_rate=Decimal("0"),
                    open=Decimal(cells[1]),
                    high=Decimal(cells[1]),
                    low=Decimal(cells[1]),
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return rows

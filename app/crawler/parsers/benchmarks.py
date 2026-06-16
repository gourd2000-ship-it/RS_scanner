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

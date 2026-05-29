from decimal import Decimal

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from app.schemas.market_data import DailyPricePayload


def parse_daily_prices(html: str) -> list[DailyPricePayload]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table.type2 tr"):
        cells = [td.get_text(strip=True).replace(",", "") for td in tr.select("td")]
        if len(cells) < 7 or not cells[0]:
            continue
        try:
            rows.append(
                DailyPricePayload(
                    trade_date=parse_date(cells[0]).date(),
                    close=Decimal(cells[1]),
                    change_rate=Decimal("0"),
                    open=Decimal(cells[3]),
                    high=Decimal(cells[4]),
                    low=Decimal(cells[5]),
                    volume=int(cells[6]),
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return rows

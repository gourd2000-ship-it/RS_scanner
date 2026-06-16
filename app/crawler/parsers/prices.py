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
            close = Decimal(cells[1])
            raw_open = Decimal(cells[3]) if cells[3] else Decimal("0")
            raw_high = Decimal(cells[4]) if cells[4] else Decimal("0")
            raw_low = Decimal(cells[5]) if cells[5] else Decimal("0")
            volume = int(cells[6]) if cells[6] else 0

            # 거래정지: open/high/low가 0이고 close가 있는 경우 → 도지 캔들로 정규화
            if raw_open == 0 and raw_high == 0 and raw_low == 0 and close > 0:
                raw_open = raw_high = raw_low = close

            rows.append(
                DailyPricePayload(
                    trade_date=parse_date(cells[0]).date(),
                    close=close,
                    change_rate=Decimal("0"),
                    open=raw_open,
                    high=raw_high,
                    low=raw_low,
                    volume=volume,
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return rows

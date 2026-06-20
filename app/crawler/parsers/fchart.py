import json
import re
from datetime import date
from decimal import Decimal

from app.schemas.market_data import DailyPricePayload


def parse_fchart_prices(raw_text: str) -> list[DailyPricePayload]:
    """Naver fchart API 응답을 DailyPricePayload 리스트로 변환 (수정주가)."""
    text = raw_text.strip()
    if not text:
        return []

    # 비표준 JSON 처리: single-quote → double-quote, trailing comma 제거
    cleaned = text.replace("'", '"')
    cleaned = re.sub(r",\s*]", "]", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list) or len(data) < 2:
        return []

    rows: list[DailyPricePayload] = []
    for entry in data[1:]:
        if not isinstance(entry, list) or len(entry) < 6:
            continue
        date_str = str(entry[0]).strip().strip('"')
        if len(date_str) != 8 or not date_str.isdigit():
            continue

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

    return sorted(rows, key=lambda r: r.trade_date)

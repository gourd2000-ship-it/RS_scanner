import logging
from decimal import Decimal

from app.schemas.market_data import DailyPricePayload

logger = logging.getLogger(__name__)

MIN_HALT_DAYS = 5


def detect_corporate_action(
    prices: list[DailyPricePayload],
    threshold: Decimal = Decimal("3"),
) -> bool:
    """거래정지 + 가격 불연속 패턴으로 기업 이벤트(액면분할/병합/감자) 감지.

    연속 volume=0 구간(5일+) 전후 종가 비율이 threshold 배를 초과하면 True.
    """
    if len(prices) < MIN_HALT_DAYS + 2:
        return False

    i = 0
    n = len(prices)
    while i < n:
        if prices[i].volume != 0:
            i += 1
            continue

        halt_start = i
        while i < n and prices[i].volume == 0:
            i += 1
        halt_length = i - halt_start

        if halt_length < MIN_HALT_DAYS:
            continue

        before_idx = halt_start - 1
        after_idx = i
        if before_idx < 0 or after_idx >= n:
            continue

        before_close = prices[before_idx].close
        after_close = prices[after_idx].close
        if before_close <= 0:
            continue

        ratio = after_close / before_close
        if ratio > threshold or (Decimal("1") / ratio) > threshold:
            logger.info(
                "기업이벤트 감지: %s~%s 거래정지(%d일), 가격비율=%.1f배",
                prices[halt_start].trade_date,
                prices[i - 1].trade_date if i - 1 < n else "?",
                halt_length,
                float(ratio),
            )
            return True

    return False

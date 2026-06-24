import logging
from decimal import Decimal

from app.schemas.market_data import DailyPricePayload

logger = logging.getLogger(__name__)

MIN_HALT_DAYS = 5
DAILY_PRICE_LIMIT = Decimal("0.305")


def detect_corporate_action(
    prices: list[DailyPricePayload],
    threshold: Decimal = Decimal("3"),
) -> bool:
    """기업 이벤트(액면분할/병합/감자) 감지.

    두 가지 패턴을 검사한다:
    1) 거래정지(volume=0, 5일+) 전후 가격 비율이 threshold 배 초과
    2) 일일 종가 변동률이 가격제한(±30%)을 초과 (한국 주식시장 가격제한 위반)
    """
    if len(prices) < 2:
        return False

    if _detect_halt_discontinuity(prices, threshold):
        return True

    if _detect_price_limit_breach(prices):
        return True

    return False


def _detect_halt_discontinuity(
    prices: list[DailyPricePayload],
    threshold: Decimal,
) -> bool:
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
                "기업이벤트 감지(거래정지): %s~%s (%d일), 가격비율=%.1f배",
                prices[halt_start].trade_date,
                prices[i - 1].trade_date if i - 1 < n else "?",
                halt_length,
                float(ratio),
            )
            return True

    return False


RS_LOOKBACK_DAYS = 253


def _detect_price_limit_breach(
    prices: list[DailyPricePayload],
    lookback: int = RS_LOOKBACK_DAYS,
) -> bool:
    """RS 계산 기간(최근 ~12개월) 내 일일 종가 변동이 가격제한(±30%)을 초과하면 기업 액션으로 판단."""
    start = max(1, len(prices) - lookback)
    for i in range(start, len(prices)):
        prev_close = prices[i - 1].close
        if prev_close <= 0:
            continue
        daily_ret = prices[i].close / prev_close - Decimal("1")
        if abs(daily_ret) > DAILY_PRICE_LIMIT:
            logger.info(
                "기업이벤트 감지(가격제한 초과): %s, 변동률=%.1f%%",
                prices[i].trade_date,
                float(daily_ret * 100),
            )
            return True
    return False


def compute_adjustment_factors(prices: list[DailyPricePayload]) -> list[Decimal]:
    """가격제한 초과 변동에 대한 후향 보정 계수 리스트를 반환.

    반환된 리스트의 각 원소를 해당 인덱스의 close에 곱하면 보정 종가가 된다.
    최신 가격 기준으로 보정하므로 마지막 원소는 항상 1.
    """
    n = len(prices)
    factors = [Decimal("1")] * n

    for i in range(n - 1, 0, -1):
        prev_close = prices[i - 1].close
        if prev_close <= 0:
            continue
        daily_ret = prices[i].close / prev_close - Decimal("1")
        if abs(daily_ret) > DAILY_PRICE_LIMIT:
            adjustment = prices[i].close / prev_close
            for j in range(i):
                factors[j] *= adjustment

    return factors

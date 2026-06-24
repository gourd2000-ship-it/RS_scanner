from datetime import date, timedelta
from decimal import Decimal

from app.schemas.market_data import DailyPricePayload
from app.services.rs.corporate_action_filter import detect_corporate_action


def _make_prices(
    days: int = 30,
    close: int = 1000,
    volume: int = 100000,
    halt_start: int | None = None,
    halt_days: int = 0,
    after_close: int | None = None,
) -> list[DailyPricePayload]:
    """테스트용 가격 데이터 생성.

    halt_start일째부터 halt_days일간 volume=0, 이후 after_close로 가격 변경.
    """
    rows = []
    start = date(2026, 1, 1)
    current_close = close
    for i in range(days):
        in_halt = halt_start is not None and halt_start <= i < halt_start + halt_days
        if in_halt:
            vol = 0
        elif halt_start is not None and i == halt_start + halt_days and after_close is not None:
            current_close = after_close
            vol = volume
        else:
            vol = volume

        rows.append(DailyPricePayload(
            trade_date=start + timedelta(days=i),
            open=Decimal(current_close),
            high=Decimal(current_close),
            low=Decimal(current_close),
            close=Decimal(current_close),
            volume=vol,
            change_rate=Decimal("0"),
        ))
    return rows


class TestCorporateActionFilter:
    def test_normal_stock_not_flagged(self):
        prices = _make_prices(days=30, close=1000, volume=50000)
        assert detect_corporate_action(prices) is False

    def test_reverse_split_10to1_detected(self):
        """액면병합 10:1 — 거래정지 후 가격 10배."""
        prices = _make_prices(
            days=30, close=4000, halt_start=10, halt_days=7, after_close=40000,
        )
        assert detect_corporate_action(prices) is True

    def test_capital_reduction_detected(self):
        """감자 — 거래정지 후 가격 18배."""
        prices = _make_prices(
            days=30, close=355, halt_start=10, halt_days=7, after_close=6500,
        )
        assert detect_corporate_action(prices) is True

    def test_short_halt_with_big_jump_detected_by_price_limit(self):
        """3일 거래정지라도 가격 10배 점프는 가격제한 초과로 감지."""
        prices = _make_prices(
            days=30, close=1000, halt_start=10, halt_days=3, after_close=10000,
        )
        assert detect_corporate_action(prices) is True

    def test_short_halt_with_small_change_not_flagged(self):
        """3일 거래정지 + 가격제한 이내 변동은 감지 안 됨."""
        prices = _make_prices(
            days=30, close=1000, halt_start=10, halt_days=3, after_close=1200,
        )
        assert detect_corporate_action(prices) is False

    def test_halt_without_price_jump_not_flagged(self):
        """거래정지 후 가격 변동이 halt threshold·가격제한 모두 미만이면 감지 안 됨."""
        prices = _make_prices(
            days=30, close=1000, halt_start=10, halt_days=7, after_close=1250,
        )
        assert detect_corporate_action(prices) is False

    def test_price_limit_breach_without_halt_detected(self):
        """거래정지 없이 가격제한(±30%) 초과 변동은 기업 액션으로 감지."""
        start = date(2026, 1, 1)
        rows = []
        for i in range(30):
            c = 1000 if i < 15 else 10000
            rows.append(DailyPricePayload(
                trade_date=start + timedelta(days=i),
                open=Decimal(c), high=Decimal(c), low=Decimal(c), close=Decimal(c),
                volume=50000, change_rate=Decimal("0"),
            ))
        assert detect_corporate_action(rows) is True

    def test_gradual_rise_within_limit_not_flagged(self):
        """매일 25%씩 상승은 가격제한 이내이므로 감지 안 됨."""
        start = date(2026, 1, 1)
        rows = []
        c = 1000
        for i in range(30):
            rows.append(DailyPricePayload(
                trade_date=start + timedelta(days=i),
                open=Decimal(int(c)), high=Decimal(int(c)), low=Decimal(int(c)),
                close=Decimal(int(c)), volume=50000, change_rate=Decimal("0"),
            ))
            c *= 1.25
        assert detect_corporate_action(rows) is False

    def test_custom_threshold(self):
        """halt threshold=5 설정 시 4배 변동(거래정지 기반)은 감지 안 되나,
        가격제한 초과 감지는 항상 동작."""
        prices = _make_prices(
            days=30, close=1000, halt_start=10, halt_days=7, after_close=4000,
        )
        # 4배 점프 → 가격제한(±30%) 초과이므로 threshold와 무관하게 감지
        assert detect_corporate_action(prices, threshold=Decimal("5")) is True
        assert detect_corporate_action(prices, threshold=Decimal("3")) is True

    def test_price_decrease_after_halt_detected(self):
        """거래정지 후 가격 급락(역분할 반대)도 감지."""
        prices = _make_prices(
            days=30, close=10000, halt_start=10, halt_days=7, after_close=1000,
        )
        assert detect_corporate_action(prices) is True

    def test_too_few_prices_returns_false(self):
        prices = _make_prices(days=5)
        assert detect_corporate_action(prices) is False

from app.core.exceptions import ValidationError
from app.schemas.market_data import DailyPricePayload


def validate_prices(prices: list[DailyPricePayload]) -> None:
    if not prices:
        raise ValidationError("no price rows fetched")
    seen_dates = set()
    for row in prices:
        if row.trade_date in seen_dates:
            raise ValidationError("duplicate trade date")
        seen_dates.add(row.trade_date)
        values = (row.open, row.high, row.low, row.close)
        if any(not value.is_finite() for value in values):
            raise ValidationError("price fields must be finite")
        if any(value <= 0 for value in values):
            raise ValidationError("price fields must be positive")
        if row.low > row.high:
            raise ValidationError("low price is higher than high price")
        if row.low > min(row.open, row.close) or row.high < max(row.open, row.close):
            raise ValidationError("OHLC values are inconsistent")
        if row.volume < 0:
            raise ValidationError("volume must not be negative")

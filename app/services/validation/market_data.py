from app.core.exceptions import ValidationError
from app.schemas.market_data import DailyPricePayload


def validate_prices(prices: list[DailyPricePayload]) -> None:
    if not prices:
        raise ValidationError("no price rows fetched")
    for row in prices:
        if row.low > row.high:
            raise ValidationError("low price is higher than high price")
        if row.close <= 0:
            raise ValidationError("close price must be positive")

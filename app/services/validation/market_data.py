from app.core.exceptions import ValidationError
from app.schemas.market_data import DailyPricePayload
from app.services.validation.rules import inspect_ohlc_row


def validate_prices(prices: list[DailyPricePayload]) -> None:
    if not prices:
        raise ValidationError("no price rows fetched")
    seen_dates = set()
    for row in prices:
        if row.trade_date in seen_dates:
            raise ValidationError("duplicate trade date")
        seen_dates.add(row.trade_date)
        findings = inspect_ohlc_row(row, rule_id="ingest_ohlc")
        if findings:
            raise ValidationError(findings[0].message)

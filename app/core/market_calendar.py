"""KRX trading-day checks used before a daily crawl is allowed to start."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays


@dataclass(frozen=True)
class MarketDayStatus:
    """Whether the KRX equity market is open on a given local date."""

    is_open: bool
    reason: str


def batch_target_date(settings, now: datetime | None = None) -> date:
    """Return today's date in the configured batch timezone."""
    now = now or datetime.now(tz=ZoneInfo("UTC"))
    try:
        return now.astimezone(ZoneInfo(settings.batch_timezone)).date()
    except Exception:
        return now.date()


@lru_cache(maxsize=None)
def _korean_public_holidays(year: int) -> holidays.HolidayBase:
    return holidays.country_holidays("KR", years=year)


def _configured_closed_dates(value: str) -> set[date]:
    """Parse the optional comma-separated ``YYYY-MM-DD`` operations override."""
    parsed: set[date] = set()
    for raw_date in value.split(","):
        raw_date = raw_date.strip()
        if not raw_date:
            continue
        try:
            parsed.add(date.fromisoformat(raw_date))
        except ValueError as exc:
            raise ValueError(
                "MARKET_CLOSED_DATES must contain comma-separated YYYY-MM-DD dates"
            ) from exc
    return parsed


def _year_end_closing_day(year: int) -> date:
    """Return KRX's final-year closing date (Dec. 31 or preceding trading day)."""
    candidate = date(year, 12, 31)
    korean_holidays = _korean_public_holidays(year)
    while candidate.weekday() >= 5 or candidate in korean_holidays:
        candidate -= timedelta(days=1)
    return candidate


def krx_market_day_status(
    target_date: date,
    *,
    configured_closed_dates: str = "",
) -> MarketDayStatus:
    """Classify a KOSPI/KOSDAQ date without making a network request.

    KRX is closed on Korean public holidays, Labour Day, and the final trading
    day of the calendar year. ``MARKET_CLOSED_DATES`` covers exchange-announced
    extraordinary closures (for example, a one-off national event) immediately.
    """
    if target_date.weekday() >= 5:
        return MarketDayStatus(False, "weekend")

    if target_date in _configured_closed_dates(configured_closed_dates):
        return MarketDayStatus(False, "configured market closure")

    if target_date.month == 5 and target_date.day == 1:
        return MarketDayStatus(False, "Labour Day")

    holiday_name = _korean_public_holidays(target_date.year).get(target_date)
    if holiday_name:
        return MarketDayStatus(False, f"Korean public holiday: {holiday_name}")

    if target_date == _year_end_closing_day(target_date.year):
        return MarketDayStatus(False, "KRX year-end closing day")

    return MarketDayStatus(True, "KRX trading day")

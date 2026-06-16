import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, RsResultPayload
from app.services.rs.policy import benchmark_for_market

logger = logging.getLogger(__name__)

TRADING_WINDOWS = {
    "3m": 63,
    "6m": 126,
    "9m": 189,
    "12m": 252,
}

MIN_REQUIRED_PRICES = max(TRADING_WINDOWS.values()) + 1


@dataclass
class SymbolSeries:
    code: str
    market: str
    prices: list[DailyPricePayload]


def _return_over_window(prices: list[DailyPricePayload], window: int) -> Decimal:
    if len(prices) <= window:
        raise ValueError(f"insufficient price history for window {window}")
    latest = prices[-1].close
    anchor = prices[-(window + 1)].close
    return (latest / anchor) - Decimal("1")


def _score(relative_returns: dict[str, Decimal]) -> Decimal:
    return (
        Decimal("0.40") * relative_returns["3m"]
        + Decimal("0.20") * relative_returns["6m"]
        + Decimal("0.20") * relative_returns["9m"]
        + Decimal("0.20") * relative_returns["12m"]
    )


def calculate_market_rs(
    market: str,
    symbol_series: Iterable[SymbolSeries],
    benchmark_prices: list[BenchmarkPricePayload],
    target_date: date | None = None,
) -> list[RsResultPayload]:
    """시장 RS 계산.

    target_date를 지정하면 해당 날짜까지의 가격만 사용하고, 모든 결과의 trade_date를
    target_date로 통일한다. 미지정 시 종목별 최신 가격 날짜를 그대로 사용한다.
    """
    benchmark_code = benchmark_for_market(market)

    effective_benchmark = (
        [p for p in benchmark_prices if p.trade_date <= target_date]
        if target_date is not None else benchmark_prices
    )
    if len(effective_benchmark) < MIN_REQUIRED_PRICES:
        logger.warning(
            "market=%s: benchmark %s has insufficient history (%d < %d days), skipping market",
            market, benchmark_code, len(effective_benchmark), MIN_REQUIRED_PRICES,
        )
        return []
    benchmark_returns = {
        key: _return_over_window(effective_benchmark, window) for key, window in TRADING_WINDOWS.items()
    }

    rows: list[RsResultPayload] = []
    skipped = 0
    for series in symbol_series:
        effective_prices = (
            [p for p in series.prices if p.trade_date <= target_date]
            if target_date is not None else series.prices
        )
        if len(effective_prices) < MIN_REQUIRED_PRICES:
            skipped += 1
            continue
        stock_returns = {key: _return_over_window(effective_prices, window) for key, window in TRADING_WINDOWS.items()}
        relative_returns = {key: stock_returns[key] - benchmark_returns[key] for key in TRADING_WINDOWS}
        score = _score(relative_returns)
        rows.append(
            RsResultPayload(
                code=series.code,
                market=market,
                trade_date=target_date if target_date is not None else effective_prices[-1].trade_date,
                return_3m=stock_returns["3m"],
                return_6m=stock_returns["6m"],
                return_9m=stock_returns["9m"],
                return_12m=stock_returns["12m"],
                relative_return_score=score,
                rs_percentile=Decimal("0"),
                rs_rating=0,
                rank_in_market=0,
            )
        )

    if skipped:
        logger.warning("market=%s: %d symbols skipped (insufficient price history, need %d days)", market, skipped, MIN_REQUIRED_PRICES)

    ordered = sorted(rows, key=lambda row: row.relative_return_score, reverse=True)
    total = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        percentile = Decimal(total - rank + 1) / Decimal(total)
        rating = max(1, min(99, int((percentile * Decimal("98")).to_integral_value()) + 1))
        row.rank_in_market = rank
        row.rs_percentile = percentile
        row.rs_rating = rating
    return ordered

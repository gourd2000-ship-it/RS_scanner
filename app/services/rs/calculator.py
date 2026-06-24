import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, RsResultPayload
from app.services.rs.policy import benchmark_for_market

logger = logging.getLogger(__name__)

# 윈저라이즈 적용 최소 종목 수 — 이보다 적으면 클리핑 생략
MIN_WINSORIZE_SAMPLES = 10


def _percentile(sorted_values: list[Decimal], pct: Decimal) -> Decimal:
    """정렬된 Decimal 리스트에서 p-th 퍼센타일을 선형보간으로 계산."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("empty list")
    if n == 1:
        return sorted_values[0]
    rank = (pct / Decimal("100")) * Decimal(n - 1)
    lower = int(rank)
    upper = lower + 1
    if upper >= n:
        return sorted_values[-1]
    frac = rank - Decimal(lower)
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


def _winsorize_bounds(
    relative_returns_by_period: dict[str, list[Decimal]],
    lower_pct: Decimal = Decimal("1"),
    upper_pct: Decimal = Decimal("99"),
) -> dict[str, tuple[Decimal, Decimal]]:
    """기간별 상대수익률 분포의 하한/상한 경계를 계산."""
    bounds: dict[str, tuple[Decimal, Decimal]] = {}
    for period, values in relative_returns_by_period.items():
        if len(values) < MIN_WINSORIZE_SAMPLES:
            bounds[period] = (Decimal("-Infinity"), Decimal("Infinity"))
            continue
        sorted_vals = sorted(values)
        lo = _percentile(sorted_vals, lower_pct)
        hi = _percentile(sorted_vals, upper_pct)
        bounds[period] = (lo, hi)
    return bounds


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


QUARTER_KEYS = ("q1", "q2", "q3", "q4")
QUARTER_WEIGHT = Decimal("0.25")


def _quarterly_returns(cumulative: dict[str, Decimal]) -> dict[str, Decimal]:
    """누적수익률에서 비중복 분기수익률을 역산."""
    one = Decimal("1")
    q1 = cumulative["3m"]
    denom_3m = one + cumulative["3m"]
    q2 = (one + cumulative["6m"]) / denom_3m - one if denom_3m else Decimal("0")
    denom_6m = one + cumulative["6m"]
    q3 = (one + cumulative["9m"]) / denom_6m - one if denom_6m else Decimal("0")
    denom_9m = one + cumulative["9m"]
    q4 = (one + cumulative["12m"]) / denom_9m - one if denom_9m else Decimal("0")
    return {"q1": q1, "q2": q2, "q3": q3, "q4": q4}


def _quarterly_score(qr: dict[str, Decimal]) -> Decimal:
    """분기별 수익률의 균등 가중합."""
    return QUARTER_WEIGHT * (qr["q1"] + qr["q2"] + qr["q3"] + qr["q4"])


def calculate_market_rs(
    market: str,
    symbol_series: Iterable[SymbolSeries],
    benchmark_prices: list[BenchmarkPricePayload],
    target_date: date | None = None,
    winsorize_lower_pct: Decimal | None = None,
    winsorize_upper_pct: Decimal | None = None,
) -> list[RsResultPayload]:
    """시장 RS 계산 (2-pass).

    target_date를 지정하면 해당 날짜까지의 가격만 사용하고, 모든 결과의 trade_date를
    target_date로 통일한다. 미지정 시 종목별 최신 가격 날짜를 그대로 사용한다.

    winsorize_lower_pct/winsorize_upper_pct를 지정하면 점수 계산 전 기간별
    상대수익률을 해당 퍼센타일로 클리핑한다. return_3m~12m 필드는 원본값 유지.
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

    # --- Pass 1: 종목별 수익률 + 상대수익률 수집 ---
    intermediates: list[tuple[str, date, dict[str, Decimal], dict[str, Decimal]]] = []
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
        trade_dt = target_date if target_date is not None else effective_prices[-1].trade_date
        intermediates.append((series.code, trade_dt, stock_returns, relative_returns))

    if skipped:
        logger.warning("market=%s: %d symbols skipped (insufficient price history, need %d days)", market, skipped, MIN_REQUIRED_PRICES)

    # --- 윈저라이즈 경계 계산 ---
    if (winsorize_lower_pct is None) != (winsorize_upper_pct is None):
        logger.warning(
            "market=%s: winsorize_lower_pct와 winsorize_upper_pct 중 하나만 설정됨 — 윈저라이즈 비활성화",
            market,
        )
    apply_winsorize = winsorize_lower_pct is not None and winsorize_upper_pct is not None
    bounds: dict[str, tuple[Decimal, Decimal]] = {}
    if apply_winsorize:
        returns_by_period: dict[str, list[Decimal]] = {key: [] for key in TRADING_WINDOWS}
        for _, _, _, rel_ret in intermediates:
            for key in TRADING_WINDOWS:
                returns_by_period[key].append(rel_ret[key])
        bounds = _winsorize_bounds(returns_by_period, winsorize_lower_pct, winsorize_upper_pct)
        clipped_count = 0
        total_values = len(intermediates) * len(TRADING_WINDOWS)
        for _, _, _, rel_ret in intermediates:
            for key in TRADING_WINDOWS:
                lo, hi = bounds[key]
                if rel_ret[key] < lo or rel_ret[key] > hi:
                    clipped_count += 1
        if clipped_count:
            logger.info(
                "market=%s: winsorize clipped %d/%d values (%.1f%%, bounds=%s~%s pct)",
                market, clipped_count, total_values,
                clipped_count / total_values * 100,
                winsorize_lower_pct, winsorize_upper_pct,
            )

    # --- Pass 2: 점수 계산 (클리핑 적용) + RsResultPayload 생성 ---
    rows: list[RsResultPayload] = []
    for code, trade_dt, stock_returns, relative_returns in intermediates:
        if apply_winsorize and bounds:
            clipped = {
                key: max(bounds[key][0], min(bounds[key][1], relative_returns[key]))
                for key in TRADING_WINDOWS
            }
        else:
            clipped = relative_returns
        score = _score(clipped)
        rows.append(
            RsResultPayload(
                code=code,
                market=market,
                trade_date=trade_dt,
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

    ordered = sorted(rows, key=lambda row: row.relative_return_score, reverse=True)
    total = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        percentile = Decimal("1") if total <= 1 else Decimal(total - rank) / Decimal(total - 1)
        rating = max(1, min(99, int((percentile * Decimal("98")).to_integral_value()) + 1))
        row.rank_in_market = rank
        row.rs_percentile = percentile
        row.rs_rating = rating
    return ordered


def calculate_combined_rs(
    symbol_series_by_market: dict[str, Iterable[SymbolSeries]],
    target_date: date | None = None,
    winsorize_lower_pct: Decimal | None = None,
    winsorize_upper_pct: Decimal | None = None,
) -> list[RsResultPayload]:
    """IBD 스타일 통합 RS 계산.

    - 분기별 수익률(Q1~Q4) 균등 가중합으로 종합 점수 산출
    - KOSPI+KOSDAQ 전체 종목 통합 순위 → 1~99 RS Rating
    - 벤치마크 대비가 아닌 절대 가격 성과 기준
    """
    # --- Pass 1: 종목별 누적수익률 + 분기수익률 수집 ---
    intermediates: list[tuple[str, str, date, dict[str, Decimal], dict[str, Decimal]]] = []
    skipped = 0

    for market, series_iter in symbol_series_by_market.items():
        for series in series_iter:
            effective_prices = (
                [p for p in series.prices if p.trade_date <= target_date]
                if target_date is not None else series.prices
            )
            if len(effective_prices) < MIN_REQUIRED_PRICES:
                skipped += 1
                continue

            cumulative = {
                key: _return_over_window(effective_prices, window)
                for key, window in TRADING_WINDOWS.items()
            }
            quarterly = _quarterly_returns(cumulative)
            trade_dt = target_date if target_date is not None else effective_prices[-1].trade_date
            intermediates.append((series.code, market, trade_dt, cumulative, quarterly))

    if skipped:
        logger.warning("통합 RS: %d종목 가격 이력 부족으로 제외 (최소 %d일 필요)", skipped, MIN_REQUIRED_PRICES)

    # --- 윈저라이즈 경계 계산 (분기수익률 대상) ---
    if (winsorize_lower_pct is None) != (winsorize_upper_pct is None):
        logger.warning("winsorize_lower_pct와 winsorize_upper_pct 중 하나만 설정됨 — 윈저라이즈 비활성화")
    apply_winsorize = winsorize_lower_pct is not None and winsorize_upper_pct is not None
    bounds: dict[str, tuple[Decimal, Decimal]] = {}
    if apply_winsorize:
        returns_by_quarter: dict[str, list[Decimal]] = {k: [] for k in QUARTER_KEYS}
        for _, _, _, _, qr in intermediates:
            for k in QUARTER_KEYS:
                returns_by_quarter[k].append(qr[k])
        bounds = _winsorize_bounds(returns_by_quarter, winsorize_lower_pct, winsorize_upper_pct)
        clipped_count = 0
        total_values = len(intermediates) * len(QUARTER_KEYS)
        for _, _, _, _, qr in intermediates:
            for k in QUARTER_KEYS:
                lo, hi = bounds[k]
                if qr[k] < lo or qr[k] > hi:
                    clipped_count += 1
        if clipped_count:
            logger.info(
                "통합 RS: winsorize clipped %d/%d values (%.1f%%, bounds=%s~%s pct)",
                clipped_count, total_values,
                clipped_count / total_values * 100,
                winsorize_lower_pct, winsorize_upper_pct,
            )

    # --- Pass 2: 점수 계산 + RsResultPayload 생성 ---
    rows: list[RsResultPayload] = []
    for code, market, trade_dt, cumulative, quarterly in intermediates:
        if apply_winsorize and bounds:
            clipped = {
                k: max(bounds[k][0], min(bounds[k][1], quarterly[k]))
                for k in QUARTER_KEYS
            }
        else:
            clipped = quarterly
        score = _quarterly_score(clipped)
        rows.append(
            RsResultPayload(
                code=code,
                market=market,
                trade_date=trade_dt,
                return_3m=cumulative["3m"],
                return_6m=cumulative["6m"],
                return_9m=cumulative["9m"],
                return_12m=cumulative["12m"],
                relative_return_score=score,
                rs_percentile=Decimal("0"),
                rs_rating=0,
                rank_in_market=0,
            )
        )

    # --- 통합 순위 (전체 시장 합산) ---
    ordered = sorted(rows, key=lambda row: row.relative_return_score, reverse=True)
    total = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        percentile = Decimal("1") if total <= 1 else Decimal(total - rank) / Decimal(total - 1)
        rating = max(1, min(99, int((percentile * Decimal("98")).to_integral_value()) + 1))
        row.rank_in_market = rank
        row.rs_percentile = percentile
        row.rs_rating = rating
    return ordered

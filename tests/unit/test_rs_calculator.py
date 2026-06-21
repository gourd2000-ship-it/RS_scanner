from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload
from app.services.rs.calculator import (
    MIN_WINSORIZE_SAMPLES,
    SymbolSeries,
    _percentile,
    _quarterly_returns,
    _winsorize_bounds,
    calculate_combined_rs,
    calculate_market_rs,
)


def make_series(start_close: int, step: int, days: int = 260):
    start = date(2025, 1, 1)
    rows = []
    for index in range(days):
        close = Decimal(start_close + step * index)
        rows.append(
            DailyPricePayload(
                trade_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
                change_rate=Decimal("0"),
            )
        )
    return rows


def make_benchmark(market: str, start_close: int, step: int, days: int = 260):
    start = date(2025, 1, 1)
    benchmark_code = "KOSPI_INDEX" if market == "KOSPI" else "KOSDAQ_INDEX"
    rows = []
    for index in range(days):
        close = Decimal(start_close + step * index)
        rows.append(
            BenchmarkPricePayload(
                benchmark_code=benchmark_code,
                market=market,
                trade_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=None,
                change_rate=Decimal("0"),
            )
        )
    return rows


def test_calculate_market_rs_ranks_symbols_within_market():
    benchmark = make_benchmark("KOSPI", 100, 1)
    series = [
        SymbolSeries(code="AAA", market="KOSPI", prices=make_series(100, 2)),
        SymbolSeries(code="BBB", market="KOSPI", prices=make_series(100, 1)),
    ]

    result = calculate_market_rs("KOSPI", series, benchmark)

    assert result[0].code == "AAA"
    assert result[0].rank_in_market == 1
    assert result[0].rs_rating >= result[1].rs_rating


# ---------------------------------------------------------------------------
# _percentile 단위 테스트
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_single_element(self):
        assert _percentile([Decimal("42")], Decimal("50")) == Decimal("42")

    def test_two_elements_midpoint(self):
        result = _percentile([Decimal("10"), Decimal("20")], Decimal("50"))
        assert result == Decimal("15")

    def test_boundary_zero(self):
        vals = [Decimal(i) for i in range(1, 11)]
        assert _percentile(vals, Decimal("0")) == Decimal("1")

    def test_boundary_hundred(self):
        vals = [Decimal(i) for i in range(1, 11)]
        assert _percentile(vals, Decimal("100")) == Decimal("10")

    def test_even_size_median(self):
        vals = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]
        result = _percentile(vals, Decimal("50"))
        assert result == Decimal("25")

    def test_odd_size_median(self):
        vals = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = _percentile(vals, Decimal("50"))
        assert result == Decimal("20")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _percentile([], Decimal("50"))

    def test_interpolation_precision(self):
        vals = [Decimal("0"), Decimal("100")]
        assert _percentile(vals, Decimal("25")) == Decimal("25")
        assert _percentile(vals, Decimal("75")) == Decimal("75")


# ---------------------------------------------------------------------------
# _winsorize_bounds 단위 테스트
# ---------------------------------------------------------------------------

class TestWinsorizeBounds:
    def test_below_min_samples_returns_infinite_bounds(self):
        small = {"3m": [Decimal(i) for i in range(MIN_WINSORIZE_SAMPLES - 1)]}
        bounds = _winsorize_bounds(small)
        lo, hi = bounds["3m"]
        assert lo == Decimal("-Infinity")
        assert hi == Decimal("Infinity")

    def test_exact_min_samples_calculates_bounds(self):
        vals = [Decimal(i) for i in range(MIN_WINSORIZE_SAMPLES)]
        bounds = _winsorize_bounds({"3m": vals})
        lo, hi = bounds["3m"]
        assert lo > Decimal("-Infinity")
        assert hi < Decimal("Infinity")
        assert lo < hi

    def test_bounds_are_within_data_range(self):
        vals = [Decimal(i) for i in range(100)]
        bounds = _winsorize_bounds({"6m": vals}, Decimal("5"), Decimal("95"))
        lo, hi = bounds["6m"]
        assert lo >= Decimal("0")
        assert hi <= Decimal("99")


# ---------------------------------------------------------------------------
# 윈저라이즈 통합 테스트: 극단치 회귀 + return 원본 보존
# ---------------------------------------------------------------------------

def _make_12_symbols_with_outlier():
    """종목 12개 생성. code='OUTLIER'는 극단적 상승(step=100), 나머지는 완만."""
    series = []
    for i in range(11):
        series.append(
            SymbolSeries(
                code=f"NORMAL_{i:02d}",
                market="KOSPI",
                prices=make_series(1000, step=1 + i),
            )
        )
    series.append(
        SymbolSeries(
            code="OUTLIER",
            market="KOSPI",
            prices=make_series(1000, step=100),
        )
    )
    return series


class TestWinsorizeIntegration:
    def test_outlier_dominates_without_winsorize(self):
        """윈저라이즈 미적용 시 극단치 종목이 1위를 차지한다."""
        benchmark = make_benchmark("KOSPI", 1000, 1)
        series = _make_12_symbols_with_outlier()

        result = calculate_market_rs("KOSPI", series, benchmark)

        outlier = next(r for r in result if r.code == "OUTLIER")
        assert outlier.rank_in_market == 1

    def test_winsorize_changes_outlier_rank(self):
        """윈저라이즈 적용 시 극단치 종목의 점수가 억제되어 순위가 변동한다."""
        benchmark = make_benchmark("KOSPI", 1000, 1)
        series = _make_12_symbols_with_outlier()

        result_raw = calculate_market_rs("KOSPI", series, benchmark)
        result_win = calculate_market_rs(
            "KOSPI", series, benchmark,
            winsorize_lower_pct=Decimal("1"),
            winsorize_upper_pct=Decimal("99"),
        )

        outlier_raw = next(r for r in result_raw if r.code == "OUTLIER")
        outlier_win = next(r for r in result_win if r.code == "OUTLIER")

        assert outlier_win.relative_return_score < outlier_raw.relative_return_score

    def test_return_fields_preserve_original_values(self):
        """윈저라이즈 적용 후에도 return_3m~12m 필드는 원본값을 유지한다."""
        benchmark = make_benchmark("KOSPI", 1000, 1)
        series = _make_12_symbols_with_outlier()

        result_raw = calculate_market_rs("KOSPI", series, benchmark)
        result_win = calculate_market_rs(
            "KOSPI", series, benchmark,
            winsorize_lower_pct=Decimal("1"),
            winsorize_upper_pct=Decimal("99"),
        )

        for code in ["OUTLIER", "NORMAL_00", "NORMAL_10"]:
            raw = next(r for r in result_raw if r.code == code)
            win = next(r for r in result_win if r.code == code)
            assert raw.return_3m == win.return_3m
            assert raw.return_6m == win.return_6m
            assert raw.return_9m == win.return_9m
            assert raw.return_12m == win.return_12m

    def test_few_symbols_skips_winsorize(self):
        """종목 수 < MIN_WINSORIZE_SAMPLES이면 윈저라이즈 파라미터를 전달해도 결과가 동일하다."""
        benchmark = make_benchmark("KOSPI", 1000, 1)
        series = [
            SymbolSeries(code="A", market="KOSPI", prices=make_series(1000, 2)),
            SymbolSeries(code="B", market="KOSPI", prices=make_series(1000, 50)),
        ]

        result_raw = calculate_market_rs("KOSPI", series, benchmark)
        result_win = calculate_market_rs(
            "KOSPI", series, benchmark,
            winsorize_lower_pct=Decimal("1"),
            winsorize_upper_pct=Decimal("99"),
        )

        for raw, win in zip(result_raw, result_win):
            assert raw.relative_return_score == win.relative_return_score
            assert raw.rank_in_market == win.rank_in_market

    def test_partial_winsorize_params_disables(self):
        """lower_pct만 전달하고 upper_pct=None이면 윈저라이즈가 비활성화된다."""
        benchmark = make_benchmark("KOSPI", 1000, 1)
        series = _make_12_symbols_with_outlier()

        result_none = calculate_market_rs("KOSPI", series, benchmark)
        result_partial = calculate_market_rs(
            "KOSPI", series, benchmark,
            winsorize_lower_pct=Decimal("1"),
            winsorize_upper_pct=None,
        )

        for raw, partial in zip(result_none, result_partial):
            assert raw.relative_return_score == partial.relative_return_score


# ---------------------------------------------------------------------------
# 분기별 수익률 단위 테스트
# ---------------------------------------------------------------------------

class TestQuarterlyReturns:
    def test_equal_cumulative_returns(self):
        """누적수익률이 모두 0이면 분기수익률도 모두 0."""
        cum = {"3m": Decimal("0"), "6m": Decimal("0"), "9m": Decimal("0"), "12m": Decimal("0")}
        qr = _quarterly_returns(cum)
        for k in ("q1", "q2", "q3", "q4"):
            assert qr[k] == Decimal("0")

    def test_steady_growth(self):
        """매 분기 10%씩 성장한 경우 각 분기 수익률이 동일해야 한다."""
        q = Decimal("0.10")
        c3 = (1 + q) - 1
        c6 = (1 + q) ** 2 - 1
        c9 = (1 + q) ** 3 - 1
        c12 = (1 + q) ** 4 - 1
        cum = {"3m": c3, "6m": c6, "9m": c9, "12m": c12}
        qr = _quarterly_returns(cum)
        for k in ("q1", "q2", "q3", "q4"):
            assert abs(qr[k] - q) < Decimal("0.0001")

    def test_recomposes_to_cumulative(self):
        """분기수익률로 누적수익률을 복원할 수 있어야 한다."""
        cum = {"3m": Decimal("0.15"), "6m": Decimal("0.30"), "9m": Decimal("0.50"), "12m": Decimal("0.80")}
        qr = _quarterly_returns(cum)
        one = Decimal("1")
        recomposed_12m = (one + qr["q1"]) * (one + qr["q2"]) * (one + qr["q3"]) * (one + qr["q4"]) - one
        assert abs(recomposed_12m - cum["12m"]) < Decimal("0.0001")


# ---------------------------------------------------------------------------
# 통합 RS 계산 테스트
# ---------------------------------------------------------------------------

class TestCombinedRs:
    def test_combined_ranking_across_markets(self):
        """KOSPI+KOSDAQ 종목이 하나의 순위로 통합 랭킹된다."""
        kospi = [
            SymbolSeries(code="K1", market="KOSPI", prices=make_series(100, 3)),
            SymbolSeries(code="K2", market="KOSPI", prices=make_series(100, 1)),
        ]
        kosdaq = [
            SymbolSeries(code="D1", market="KOSDAQ", prices=make_series(100, 2)),
        ]
        result = calculate_combined_rs({"KOSPI": kospi, "KOSDAQ": kosdaq})
        assert len(result) == 3
        assert result[0].code == "K1"
        assert result[0].rank_in_market == 1
        assert result[1].code == "D1"
        assert result[1].rank_in_market == 2
        assert result[2].code == "K2"
        assert result[2].rank_in_market == 3

    def test_no_benchmark_needed(self):
        """통합 RS 계산에는 벤치마크가 불필요하다."""
        series = [SymbolSeries(code="A", market="KOSPI", prices=make_series(100, 2))]
        result = calculate_combined_rs({"KOSPI": series})
        assert len(result) == 1
        assert result[0].rs_rating == 99

    def test_return_fields_store_cumulative(self):
        """return_3m~12m 필드는 누적수익률을 저장한다."""
        series = [SymbolSeries(code="A", market="KOSPI", prices=make_series(100, 2))]
        result = calculate_combined_rs({"KOSPI": series})
        r = result[0]
        assert r.return_3m > 0
        assert r.return_12m > r.return_3m

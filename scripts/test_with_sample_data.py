"""
테스트 데이터로 배치 실행
"""
import sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from app.core.database import init_db, session_scope
from app.core.logging import configure_logging
from app.services.batch.context import build_db_batch_context
from app.services.batch.run_daily_job import run_daily_job
from app.schemas.market_data import SymbolPayload, DailyPricePayload, BenchmarkPricePayload
from tests.harness.fake_source import FakePriceSource


def generate_sample_data():
    """샘플 데이터 생성"""
    # 5개 KOSPI 종목 + 3개 KOSDAQ 종목
    symbols = [
        # KOSPI
        SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
        SymbolPayload(code="000660", name="SK하이닉스", market="KOSPI"),
        SymbolPayload(code="005380", name="현대차", market="KOSPI"),
        SymbolPayload(code="035420", name="NAVER", market="KOSPI"),
        SymbolPayload(code="051910", name="LG화학", market="KOSPI"),
        # KOSDAQ
        SymbolPayload(code="247540", name="에코프로비엠", market="KOSDAQ"),
        SymbolPayload(code="086520", name="에코프로", market="KOSDAQ"),
        SymbolPayload(code="058470", name="리노공업", market="KOSDAQ"),
    ]

    # 최근 280일 데이터 생성 (12m window인 252일 + 여유)
    end_date = date(2024, 5, 28)
    dates = [end_date - timedelta(days=i) for i in range(280)]  # 일간 데이터
    dates.reverse()

    # 각 종목별 가격 데이터 (상승 추세)
    prices_by_code = {}
    base_prices = {
        "005930": 70000, "000660": 120000, "005380": 180000,
        "035420": 200000, "051910": 400000, "247540": 300000,
        "086520": 80000, "058470": 150000,
    }

    for sym in symbols:
        base = base_prices[sym.code]
        prices = []
        prev_price = base
        for i, d in enumerate(dates):
            # 점진적 상승 (5%~20% 변동)
            variation = 1.0 + (i / 280) * 0.15  # 0%~15% 상승
            close = int(base * variation)
            open_price = int(close * 0.98)  # open은 close보다 약간 낮게
            high = int(close * 1.02)  # high는 close보다 약간 높게
            low = int(close * 0.96)  # low는 close보다 낮게

            change_rate = ((close - prev_price) / prev_price * 100) if prev_price else 0

            prices.append(DailyPricePayload(
                trade_date=d,
                open=Decimal(str(open_price)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
                volume=1000000,
                change_rate=Decimal(f"{change_rate:.2f}"),
            ))
            prev_price = close
        prices_by_code[sym.code] = prices

    # 벤치마크 데이터 (KOSPI, KOSDAQ)
    benchmark_prices = {}
    for market, base_value in [("KOSPI", 2500), ("KOSDAQ", 800)]:
        prices = []
        prev_value = base_value
        for i, d in enumerate(dates):
            variation = 1.0 + (i / 280) * 0.10  # 0%~10% 상승
            close = base_value * variation
            open_value = close * 0.99
            high = close * 1.01
            low = close * 0.98

            change_rate = ((close - prev_value) / prev_value * 100) if prev_value else 0

            prices.append(BenchmarkPricePayload(
                benchmark_code=market,
                market=market,
                trade_date=d,
                open=Decimal(f"{open_value:.2f}"),
                high=Decimal(f"{high:.2f}"),
                low=Decimal(f"{low:.2f}"),
                close=Decimal(f"{close:.2f}"),
                volume=None,
                change_rate=Decimal(f"{change_rate:.2f}"),
            ))
            prev_value = close
        benchmark_prices[market] = prices

    return symbols, prices_by_code, benchmark_prices


def main():
    configure_logging()
    init_db()

    print("📦 샘플 데이터 생성 중...")
    symbols, prices_by_code, benchmark_prices = generate_sample_data()
    print(f"  - 종목: {len(symbols)}개")
    print(f"  - 가격 데이터: 종목당 {len(next(iter(prices_by_code.values())))}일")

    # FakePriceSource 생성
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code=prices_by_code,
        benchmark_prices_by_market=benchmark_prices,
    )

    print("\n🚀 배치 실행 중...")
    with session_scope() as session:
        context = build_db_batch_context(session)
        result = run_daily_job(context, source)
        print("\n✅ 배치 완료!")
        print(f"  - 종목: {result['symbols']}개")
        print(f"  - 벤치마크: {result['benchmarks']}")
        print(f"  - 가격 데이터: {sum(result['prices'].values())}건")
        print(f"  - RS 점수: {sum(result['rs_results'].values())}건")


if __name__ == "__main__":
    main()

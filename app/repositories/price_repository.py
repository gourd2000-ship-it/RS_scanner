from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload


class PriceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_symbol_prices(self, code: str, prices: Iterable[DailyPricePayload]) -> list[DailyPricePayload]:
        symbol = self.session.scalar(select(Symbol).where(Symbol.code == code))
        if symbol is None:
            raise KeyError(f"missing symbol {code}")

        incoming = sorted(prices, key=lambda row: row.trade_date)
        dates = [row.trade_date for row in incoming]
        existing = {
            row.trade_date: row
            for row in self.session.scalars(
                select(DailyPrice).where(DailyPrice.symbol_id == symbol.id, DailyPrice.trade_date.in_(dates))
            ).all()
        }

        for payload in incoming:
            row = existing.get(payload.trade_date)
            if row is None:
                row = DailyPrice(
                    symbol_id=symbol.id,
                    trade_date=payload.trade_date,
                    open=payload.open,
                    high=payload.high,
                    low=payload.low,
                    close=payload.close,
                    volume=payload.volume,
                    change_rate=payload.change_rate,
                )
                self.session.add(row)
            else:
                row.open = payload.open
                row.high = payload.high
                row.low = payload.low
                row.close = payload.close
                row.volume = payload.volume
                row.change_rate = payload.change_rate

        self.session.flush()
        return self.get_symbol_prices(code)

    def save_benchmark_prices(
        self, benchmark_code: str, prices: Iterable[BenchmarkPricePayload]
    ) -> list[BenchmarkPricePayload]:
        benchmark = self.session.scalar(select(Benchmark).where(Benchmark.benchmark_code == benchmark_code))
        if benchmark is None:
            raise KeyError(f"missing benchmark {benchmark_code}")

        incoming = sorted(prices, key=lambda row: row.trade_date)
        dates = [row.trade_date for row in incoming]
        existing = {
            row.trade_date: row
            for row in self.session.scalars(
                select(BenchmarkDailyPrice).where(
                    BenchmarkDailyPrice.benchmark_id == benchmark.id,
                    BenchmarkDailyPrice.trade_date.in_(dates),
                )
            ).all()
        }

        for payload in incoming:
            row = existing.get(payload.trade_date)
            if row is None:
                row = BenchmarkDailyPrice(
                    benchmark_id=benchmark.id,
                    trade_date=payload.trade_date,
                    open=payload.open,
                    high=payload.high,
                    low=payload.low,
                    close=payload.close,
                    volume=payload.volume,
                    change_rate=payload.change_rate,
                )
                self.session.add(row)
            else:
                row.open = payload.open
                row.high = payload.high
                row.low = payload.low
                row.close = payload.close
                row.volume = payload.volume
                row.change_rate = payload.change_rate

        self.session.flush()
        return self.get_benchmark_prices(benchmark_code)

    def get_symbol_prices(self, code: str) -> list[DailyPricePayload]:
        rows = self.session.execute(
            select(DailyPrice)
            .join(Symbol, Symbol.id == DailyPrice.symbol_id)
            .where(Symbol.code == code)
            .order_by(DailyPrice.trade_date)
        ).scalars()
        return [
            DailyPricePayload(
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                change_rate=row.change_rate,
            )
            for row in rows
        ]

    def get_benchmark_prices(self, benchmark_code: str) -> list[BenchmarkPricePayload]:
        market = self.session.scalar(select(Benchmark.market).where(Benchmark.benchmark_code == benchmark_code))
        rows = self.session.execute(
            select(BenchmarkDailyPrice)
            .join(Benchmark, Benchmark.id == BenchmarkDailyPrice.benchmark_id)
            .where(Benchmark.benchmark_code == benchmark_code)
            .order_by(BenchmarkDailyPrice.trade_date)
        ).scalars()
        return [
            BenchmarkPricePayload(
                benchmark_code=benchmark_code,
                market=market,
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                change_rate=row.change_rate,
            )
            for row in rows
        ]

    def get_latest_symbol_trade_date(self, code: str) -> date | None:
        return self.session.scalar(
            select(func.max(DailyPrice.trade_date))
            .join(Symbol, Symbol.id == DailyPrice.symbol_id)
            .where(Symbol.code == code)
        )

    def get_latest_benchmark_trade_date(self, benchmark_code: str) -> date | None:
        return self.session.scalar(
            select(func.max(BenchmarkDailyPrice.trade_date))
            .join(Benchmark, Benchmark.id == BenchmarkDailyPrice.benchmark_id)
            .where(Benchmark.benchmark_code == benchmark_code)
        )

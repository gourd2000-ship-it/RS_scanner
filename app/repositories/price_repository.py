from collections.abc import Iterable
from datetime import date, datetime
from hashlib import sha256
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.models.daily_price import DailyPrice
from app.models.data_quality import BenchmarkObservation, PriceObservation
from app.models.symbol import Symbol
from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload


class PriceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_symbol_prices(
        self,
        code: str,
        prices: Iterable[DailyPricePayload],
        *,
        crawl_job_id: int | None = None,
        provider: str = "naver",
        parser_version: str | None = None,
    ) -> list[DailyPricePayload]:
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
                    source=provider,
                )
                self.session.add(row)
            else:
                row.open = payload.open
                row.high = payload.high
                row.low = payload.low
                row.close = payload.close
                row.volume = payload.volume
                row.change_rate = payload.change_rate
            row.source = provider

        self._append_price_observations(
            symbol.id,
            incoming,
            crawl_job_id=crawl_job_id,
            provider=provider,
            parser_version=parser_version,
        )

        self.session.flush()
        return self.get_symbol_prices(code)

    def save_symbol_prices_bulk(
        self,
        prices_by_code: dict[str, Iterable[DailyPricePayload]],
        *,
        crawl_job_id: int | None = None,
        provider: str = "naver",
        parser_version: str | None = None,
    ) -> dict[str, list[DailyPricePayload]]:
        """여러 종목의 EOD 행을 하나의 transaction flush로 upsert한다."""
        grouped = {
            code: sorted(list(rows), key=lambda row: row.trade_date)
            for code, rows in prices_by_code.items()
            if rows
        }
        if not grouped:
            return {}

        codes = list(grouped)
        symbols = self.session.scalars(
            select(Symbol).where(Symbol.code.in_(codes))
        ).all()
        symbol_by_code = {symbol.code: symbol for symbol in symbols}
        missing_codes = set(codes) - set(symbol_by_code)
        if missing_codes:
            raise KeyError(f"missing symbols: {', '.join(sorted(missing_codes))}")

        symbol_ids = [symbol.id for symbol in symbols]
        dates = {
            row.trade_date
            for rows in grouped.values()
            for row in rows
        }
        existing = {
            (row.symbol_id, row.trade_date): row
            for row in self.session.scalars(
                select(DailyPrice).where(
                    DailyPrice.symbol_id.in_(symbol_ids),
                    DailyPrice.trade_date.in_(dates),
                )
            ).all()
        }

        for code, rows in grouped.items():
            symbol_id = symbol_by_code[code].id
            for payload in rows:
                row = existing.get((symbol_id, payload.trade_date))
                if row is None:
                    self.session.add(
                        DailyPrice(
                            symbol_id=symbol_id,
                            trade_date=payload.trade_date,
                            open=payload.open,
                            high=payload.high,
                            low=payload.low,
                            close=payload.close,
                            volume=payload.volume,
                            change_rate=payload.change_rate,
                            source=provider,
                        )
                    )
                else:
                    row.open = payload.open
                    row.high = payload.high
                    row.low = payload.low
                    row.close = payload.close
                    row.volume = payload.volume
                    row.change_rate = payload.change_rate
                    row.source = provider

            self._append_price_observations(
                symbol_id,
                rows,
                crawl_job_id=crawl_job_id,
                provider=provider,
                parser_version=parser_version,
            )

        self.session.flush()
        return {code: self.get_symbol_prices(code) for code in grouped}

    def save_benchmark_prices(
        self,
        benchmark_code: str,
        prices: Iterable[BenchmarkPricePayload],
        *,
        crawl_job_id: int | None = None,
        provider: str = "naver",
        parser_version: str | None = None,
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

        self._append_benchmark_observations(
            benchmark.id,
            incoming,
            crawl_job_id=crawl_job_id,
            provider=provider,
            parser_version=parser_version,
        )

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

    @staticmethod
    def _payload_hash(payload: object, *, provider: str) -> str:
        values = {
            "provider": provider,
            "trade_date": getattr(payload, "trade_date").isoformat(),
            "open": str(getattr(payload, "open")),
            "high": str(getattr(payload, "high")),
            "low": str(getattr(payload, "low")),
            "close": str(getattr(payload, "close")),
            "volume": getattr(payload, "volume"),
            "change_rate": str(getattr(payload, "change_rate")),
        }
        return sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _append_price_observations(
        self,
        symbol_id: int,
        prices: Iterable[DailyPricePayload],
        *,
        crawl_job_id: int | None,
        provider: str,
        parser_version: str | None,
    ) -> None:
        observed_at = datetime.utcnow()
        for payload in prices:
            self.session.add(
                PriceObservation(
                    symbol_id=symbol_id,
                    crawl_job_id=crawl_job_id,
                    trade_date=payload.trade_date,
                    open=payload.open,
                    high=payload.high,
                    low=payload.low,
                    close=payload.close,
                    volume=payload.volume,
                    change_rate=payload.change_rate,
                    provider=provider,
                    parser_version=parser_version,
                    payload_hash=self._payload_hash(payload, provider=provider),
                    observed_at=observed_at,
                )
            )

    def _append_benchmark_observations(
        self,
        benchmark_id: int,
        prices: Iterable[BenchmarkPricePayload],
        *,
        crawl_job_id: int | None,
        provider: str,
        parser_version: str | None,
    ) -> None:
        observed_at = datetime.utcnow()
        for payload in prices:
            self.session.add(
                BenchmarkObservation(
                    benchmark_id=benchmark_id,
                    crawl_job_id=crawl_job_id,
                    trade_date=payload.trade_date,
                    open=payload.open,
                    high=payload.high,
                    low=payload.low,
                    close=payload.close,
                    volume=payload.volume,
                    change_rate=payload.change_rate,
                    provider=provider,
                    parser_version=parser_version,
                    payload_hash=self._payload_hash(payload, provider=provider),
                    observed_at=observed_at,
                )
            )

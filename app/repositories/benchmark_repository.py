from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.services.rs.policy import MARKET_BENCHMARKS


class BenchmarkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_defaults(self) -> dict[str, Benchmark]:
        existing = {
            row.benchmark_code: row for row in self.session.scalars(select(Benchmark)).all()
        }
        for market, benchmark_code in MARKET_BENCHMARKS.items():
            row = existing.get(benchmark_code)
            if row is None:
                row = Benchmark(benchmark_code=benchmark_code, market=market, name=market)
                self.session.add(row)
                existing[benchmark_code] = row
            else:
                row.market = market
                row.name = market

        self.session.flush()
        return existing

    def get_by_market(self, market: str) -> Benchmark:
        benchmark_code = MARKET_BENCHMARKS[market]
        row = self.session.scalar(select(Benchmark).where(Benchmark.benchmark_code == benchmark_code))
        if row is None:
            raise KeyError(f"missing benchmark for market {market}")
        return row

    def get_code_to_id_map(self) -> dict[str, int]:
        rows = self.session.scalars(select(Benchmark)).all()
        return {row.benchmark_code: row.id for row in rows}

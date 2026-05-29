class MemoryBenchmarkRepository:
    def __init__(self) -> None:
        self._benchmarks = {
            "KOSPI_INDEX": {"benchmark_code": "KOSPI_INDEX", "market": "KOSPI", "name": "KOSPI"},
            "KOSDAQ_INDEX": {"benchmark_code": "KOSDAQ_INDEX", "market": "KOSDAQ", "name": "KOSDAQ"},
        }

    def upsert_defaults(self) -> dict[str, dict[str, str]]:
        return self._benchmarks

    def get_by_market(self, market: str) -> dict[str, str]:
        for benchmark in self._benchmarks.values():
            if benchmark["market"] == market:
                return benchmark
        raise KeyError(market)

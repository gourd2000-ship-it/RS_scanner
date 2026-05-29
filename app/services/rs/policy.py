MARKET_BENCHMARKS = {
    "KOSPI": "KOSPI_INDEX",
    "KOSDAQ": "KOSDAQ_INDEX",
}


def benchmark_for_market(market: str) -> str:
    return MARKET_BENCHMARKS[market]

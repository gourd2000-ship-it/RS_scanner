import json
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.base import Base
import app.models  # noqa: F401
from app.crawler.sources.naver import NaverPriceSource
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.services.batch.context import build_db_batch_context
from app.services.batch.sync_benchmarks import sync_benchmarks


def _response(code: str, rows: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "resultCode": "success",
            "result": {
                "siseList": [
                    {
                        "cd": code,
                        "dt": day,
                        "ncv": close,
                        "cv": "1.25",
                        "cr": "0.05",
                        "ov": close,
                        "hv": close,
                        "lv": close,
                    }
                    for day, close in rows
                ]
            },
        }
    )


class PageClient:
    def __init__(self, values: dict[str, str | list[str]]) -> None:
        self.values = values

    def get(self, url: str) -> str:
        value = self.values[url]
        if isinstance(value, list):
            return value.pop(0)
        return value


def test_naver_benchmark_sync_persists_both_markets_and_is_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            context = build_db_batch_context(session)
            values = {}
            for market, close in (("KOSPI", "3455.37"), ("KOSDAQ", "850.12")):
                base_url = (
                    "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
                    f"?code={market}&pageSize=100&page="
                )
                values[base_url + "1"] = _response(
                    market,
                    [("20260930", close), ("20260929", close)],
                )
                values[base_url + "2"] = _response(market, [])
            source = NaverPriceSource(client=PageClient(values))

            first = sync_benchmarks(context, source)
            session.commit()

            assert {
                market: [row.trade_date for row in rows]
                for market, rows in first.items()
            } == {
                "KOSPI": [date(2026, 9, 29), date(2026, 9, 30)],
                "KOSDAQ": [date(2026, 9, 29), date(2026, 9, 30)],
            }
            assert {
                market: {row.benchmark_code for row in rows}
                for market, rows in first.items()
            } == {
                "KOSPI": {"KOSPI_INDEX"},
                "KOSDAQ": {"KOSDAQ_INDEX"},
            }

            second = sync_benchmarks(context, source)
            assert all(len(rows) == 2 for rows in second.values())
            assert session.scalar(select(func.count(BenchmarkDailyPrice.id))) == 4
    finally:
        engine.dispose()


def test_naver_benchmark_sync_refreshes_latest_date_and_excludes_future_date():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            context = build_db_batch_context(session)
            context.target_date = date(2026, 9, 30)
            values = {}
            closing_values = {"KOSPI": "3456.10", "KOSDAQ": "851.20"}
            for market, morning_close in (("KOSPI", "3455.37"), ("KOSDAQ", "850.12")):
                base_url = (
                    "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
                    f"?code={market}&pageSize=100&page="
                )
                values[base_url + "1"] = [
                    _response(
                        market,
                        [
                            ("20261001", "9999.99"),
                            ("20260930", morning_close),
                            ("20260929", "3443.03"),
                        ],
                    ),
                    _response(
                        market,
                        [
                            ("20261001", "9999.99"),
                            ("20260930", closing_values[market]),
                            ("20260929", "3443.03"),
                        ],
                    ),
                ]
                values[base_url + "2"] = _response(market, [])
            source = NaverPriceSource(client=PageClient(values))

            first = sync_benchmarks(context, source)
            session.flush()
            assert all(row.trade_date <= context.target_date for rows in first.values() for row in rows)
            assert all(
                next(row for row in rows if row.trade_date == date(2026, 9, 30)).close
                == Decimal(morning_close)
                for market, rows in first.items()
                for morning_close in ["3455.37" if market == "KOSPI" else "850.12"]
            )

            second = sync_benchmarks(context, source)

            assert all(
                next(row for row in rows if row.trade_date == date(2026, 9, 30)).close
                == Decimal(closing_values[market])
                for market, rows in second.items()
            )
            assert session.scalar(select(func.count(BenchmarkDailyPrice.id))) == 4
    finally:
        engine.dispose()

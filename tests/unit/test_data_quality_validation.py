from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.base import Base
from app.models.benchmark import Benchmark
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.services.validation.data_quality import ValidationPolicy, validate_crawl_job
from app.services.validation.rules import inspect_ohlc_row


def _price(symbol_id: int, trade_date: date, close: int) -> DailyPrice:
    return DailyPrice(
        symbol_id=symbol_id,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=100,
        change_rate=Decimal("0"),
        source="test",
    )


def test_ohlc_rule_returns_structured_exclusion_finding():
    row = _price(1, date(2026, 8, 11), 100)
    row.high = Decimal("90")

    findings = inspect_ohlc_row(row)

    assert len(findings) == 1
    assert findings[0].reason_code == "INVALID_OHLC"
    assert findings[0].decision == "EXCLUDE"
    assert findings[0].case_status == "auto_resolved"


def test_validation_replay_records_freshness_and_coverage_cases():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_date = date(2026, 8, 11)

    with Session(engine) as session:
        symbols = [
            Symbol(code="A", name="Alpha", market="KOSPI", is_active=True, symbol_type="stock"),
            Symbol(code="B", name="Beta", market="KOSPI", is_active=True, symbol_type="stock"),
        ]
        session.add_all(symbols)
        session.flush()
        session.add_all(
            [
                Benchmark(
                    benchmark_code="KOSPI_INDEX",
                    name="KOSPI",
                    market="KOSPI",
                    created_at=datetime.utcnow(),
                ),
                Benchmark(
                    benchmark_code="KOSDAQ_INDEX",
                    name="KOSDAQ",
                    market="KOSDAQ",
                    created_at=datetime.utcnow(),
                ),
            ]
        )
        job = CrawlJob(
            job_type="daily_full",
            started_at=datetime.utcnow(),
            status="completed_with_errors",
            symbols_total=2,
            symbols_succeeded=1,
            symbols_failed=1,
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                CrawlTargetResult(
                    job_id=job.id,
                    step_name="prices",
                    target_type="stock",
                    target_key="A",
                    status="fetched",
                    trade_date=target_date,
                ),
                CrawlTargetResult(
                    job_id=job.id,
                    step_name="prices",
                    target_type="stock",
                    target_key="B",
                    status="failed",
                    trade_date=target_date - timedelta(days=1),
                ),
            ]
        )
        session.add_all(
            [
                _price(symbols[0].id, target_date - timedelta(days=1), 99),
                _price(symbols[0].id, target_date, 100),
                _price(symbols[1].id, target_date - timedelta(days=2), 50),
            ]
        )
        session.commit()

        result = validate_crawl_job(
            session,
            job.id,
            target_date=target_date,
            policy=ValidationPolicy(
                mode="report_only",
                validator_version="test",
                coverage_warning=Decimal("0.97"),
                coverage_block=Decimal("0.90"),
                stale_warning_lag_days=1,
                stale_block_lag_days=5,
                extreme_return_threshold=Decimal("0.30"),
                require_benchmark=False,
                min_history_rows=2,
            ),
        )

        assert result.run.trade_date == target_date
        assert result.run.expected_symbols == 2
        assert result.run.fresh_symbols == 1
        assert result.run.stale_symbols == 1
        assert result.run.validation_status == "blocked"
        reasons = {case.reason_code for case in result.cases}
        assert "RS_INPUT_STALE" in reasons
        assert "COVERAGE_BELOW_POLICY" in reasons

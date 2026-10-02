"""BT10 RS uses only immutable dataset prices available on each target date."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetMembership, BacktestDatasetPrice
from app.services.historical_rs import HistoricalRsPolicy, calculate_historical_rs


def _dataset(session: Session) -> BacktestDataset:
    dataset = BacktestDataset(
        dataset_id="rs-test", manifest_hash="a" * 64, range_start=date(2020, 1, 1),
        range_end=date(2020, 12, 31), markets=["KOSPI"], reconstruction_mode="historical_reconstructed",
        adjustment_policy="kiwoom:1", policy_version="gaps-v1", manifest={},
    )
    session.add(dataset)
    session.flush()
    start = date(2020, 1, 1)
    target = start + timedelta(days=252)
    for instrument_id, multiplier in ((1, Decimal("1")), (2, Decimal("2")), (3, Decimal("1"))):
        count = 253 if instrument_id != 3 else 20
        first_date = start if instrument_id != 3 else target - timedelta(days=count - 1)
        for offset in range(count):
            close = (Decimal("100") + Decimal(offset) * multiplier)
            dataset.prices.append(BacktestDatasetPrice(
                instrument_id=instrument_id, source_symbol_id=instrument_id, code=f"00000{instrument_id}", name=f"표본 {instrument_id}", market="KOSPI",
                trade_date=first_date + timedelta(days=offset), open=close, high=close, low=close, close=close,
                volume=100, change_rate=Decimal("0"), provider="kiwoom",
            ))
        dataset.memberships.append(BacktestDatasetMembership(
            instrument_id=instrument_id, trade_date=target, market="KOSPI", security_type="stock",
            membership_evidence_state="observed", trading_status="trading", price_expectation="expected", event_revision_hashes=[],
        ))
    session.flush()
    return dataset


def test_historical_rs_uses_only_prices_at_or_before_target_and_records_insufficient_history():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = _dataset(session)
        first = calculate_historical_rs(session, dataset_id=dataset.dataset_id, policy=HistoricalRsPolicy(version="rs-historical-v1"))
        available = {row.instrument_id: row for row in first.rows if row.status == "available"}
        insufficient = next(row for row in first.rows if row.instrument_id == 3)
        assert set(available) == {1, 2}
        assert insufficient.reason_code == "insufficient_history"
        assert insufficient.required_observations == 253

        # A later copied price must not alter D's fixed calculation.
        dataset.prices.append(BacktestDatasetPrice(
            instrument_id=1, source_symbol_id=1, code="000001", name="표본 1", market="KOSPI",
            trade_date=date(2021, 1, 1), open=Decimal("9999"), high=Decimal("9999"), low=Decimal("9999"), close=Decimal("9999"),
            volume=100, change_rate=Decimal("0"), provider="kiwoom",
        ))
        second = calculate_historical_rs(session, dataset_id=dataset.dataset_id, policy=HistoricalRsPolicy(version="rs-historical-v1"))
        assert second.result_hash == first.result_hash
        assert dataset.manifest["rs"]["formula_version"] == "rs-historical-v1"
        assert dataset.final_manifest_hash

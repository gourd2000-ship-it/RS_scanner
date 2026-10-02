"""BT09 snapshots retain the exact price and universe evidence they published."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.daily_price import DailyPrice
from app.models.data_quality import PriceObservation
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.backtest_snapshot import BacktestDatasetRequest, create_backtest_dataset, get_backtest_dataset


def _event(instrument_id: int, market: str) -> ListingEventInput:
    return ListingEventInput(
        instrument_id=instrument_id,
        source="approved_export",
        source_contract_version="test-v1",
        source_record_key="listing",
        event_type="listed",
        effective_from=date(2010, 1, 1),
        market=market,
        evidence_state="observed",
        payload={"market": market},
    )


def _price(symbol_id: int, close: str) -> DailyPrice:
    value = Decimal(close)
    return DailyPrice(
        symbol_id=symbol_id, trade_date=date(2020, 1, 2), open=value, high=value + 1,
        low=value - 1, close=value, volume=100, change_rate=Decimal("0"), source="kiwoom",
    )


def test_dataset_copies_price_and_membership_revisions_so_later_updates_do_not_change_it():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(
            krx_short_code="000001", isin="KR7000000001", name="상폐 표본", market="KOSDAQ",
            security_type="stock", listing_status="listed",
        )
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000001", name="상폐 표본", market="KOSDAQ", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        session.add(_price(symbol.id, "100"))
        ListingHistoryRepository(session).ingest(
            _event(instrument.id, "KOSDAQ"), source_file_hash="a" * 64,
            observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        session.flush()

        first = create_backtest_dataset(
            session,
            BacktestDatasetRequest(
                start=date(2020, 1, 2), end=date(2020, 1, 2), markets=("KOSDAQ",),
                adjustment_policy="kiwoom:1", policy_version="historical-gaps-v1",
                preparation_start=date(2019, 1, 1),
            ),
        )
        first_hash = first.manifest_hash
        assert first.prices[0].close == Decimal("100")
        assert first.memberships[0].market == "KOSDAQ"
        assert first.manifest["replay_capability"]["historical_reconstructed"] == "available"
        assert "price_lineage" not in first.manifest
        assert len(first.manifest["watermark"]["price_snapshot_hash"]) == 64
        assert first.manifest["coverage"]["observed_expected_price_count"] == 1
        session.commit()
        session.refresh(first)
        assert first.manifest["coverage"]["observed_expected_price_count"] == 1

        session.get(DailyPrice, 1).close = Decimal("200")
        ListingHistoryRepository(session).ingest(
            _event(instrument.id, "KOSPI"), source_file_hash="b" * 64,
            observed_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        )
        session.flush()
        second = create_backtest_dataset(
            session,
            BacktestDatasetRequest(
                start=date(2020, 1, 2), end=date(2020, 1, 2), markets=("KOSPI",),
                adjustment_policy="kiwoom:1", policy_version="historical-gaps-v1",
                preparation_start=date(2019, 1, 1),
            ),
        )

        assert first.manifest_hash == first_hash
        assert first.prices[0].close == Decimal("100")
        assert first.memberships[0].market == "KOSDAQ"
        assert second.prices[0].close == Decimal("200")
        assert second.memberships[0].market == "KOSPI"
        assert second.manifest_hash != first_hash


def test_as_known_at_uses_append_only_observations_and_records_partial_capability():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000002", isin="KR7000000002", name="관측 표본", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000002", name="관측 표본", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        session.add(_price(symbol.id, "200"))
        ListingHistoryRepository(session).ingest(
            _event(instrument.id, "KOSPI"), source_file_hash="c" * 64,
            observed_at=datetime(2019, 1, 1, tzinfo=timezone.utc),
        )
        for close, seen, payload_hash in (("100", datetime(2020, 1, 3, tzinfo=timezone.utc), "d" * 64), ("200", datetime(2021, 1, 3, tzinfo=timezone.utc), "e" * 64)):
            value = Decimal(close)
            session.add(PriceObservation(
                symbol_id=symbol.id, trade_date=date(2020, 1, 2), open=value, high=value + 1,
                low=value - 1, close=value, volume=100, change_rate=Decimal("0"), provider="kiwoom",
                adjustment_type="1", payload_hash=payload_hash, observed_at=seen,
            ))
        ListingHistoryRepository(session).ingest(
            _event(instrument.id, "KOSDAQ"), source_file_hash="f" * 64,
            observed_at=datetime(2021, 1, 4, tzinfo=timezone.utc),
        )
        session.flush()

        dataset = create_backtest_dataset(
            session,
            BacktestDatasetRequest(
                start=date(2020, 1, 2), end=date(2020, 1, 2), markets=("KOSPI",),
                adjustment_policy="kiwoom:1", policy_version="historical-gaps-v1",
                reconstruction_mode="as_known_at", as_known_at=datetime(2020, 6, 1, tzinfo=timezone.utc),
            ),
        )

        assert dataset.prices[0].close == Decimal("100")
        assert dataset.memberships[0].market == "KOSPI"
        assert dataset.manifest["as_known_at"] == "2020-06-01T00:00:00+00:00"
        assert dataset.manifest["replay_capability"]["as_known_at"] == "available"


def test_retention_expiry_hides_a_dataset_without_mutating_its_materialized_rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000003", isin="KR7000000003", name="보존", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000003", name="보존", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        session.add(_price(symbol.id, "100"))
        ListingHistoryRepository(session).ingest(_event(instrument.id, "KOSPI"), source_file_hash="f" * 64)
        dataset = create_backtest_dataset(
            session,
            BacktestDatasetRequest(
                start=date(2020, 1, 2), end=date(2020, 1, 2), markets=("KOSPI",),
                adjustment_policy="kiwoom:1", policy_version="historic-v1",
                retention_until=datetime(2020, 1, 4, tzinfo=timezone.utc),
            ),
        )
        price_count = len(dataset.prices)

        assert get_backtest_dataset(session, dataset.dataset_id, now=datetime(2020, 1, 5, tzinfo=timezone.utc)) is None
        assert dataset.status == "expired"
        assert len(dataset.prices) == price_count

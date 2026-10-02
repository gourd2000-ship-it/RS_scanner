"""검증된 OHLCV와 결측 상태를 같은 데이터셋 버전에 보존한다."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import PriceObservation
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository
from app.services.clean_backtest_snapshot import create_clean_backtest_dataset
from app.api.v1.endpoints.backtest import _materialized_dataset_page
from app.services.validation.cleansing_policy import CleansingSelection


def test_clean_dataset_freezes_selected_observation_and_keeps_missing_day():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000001", name="표본", market="KOSPI", security_type="stock", listing_status="listed")
        session.add(instrument)
        session.flush()
        symbol = Symbol(code="000001", name="표본", market="KOSPI", instrument_id=instrument.id)
        session.add(symbol)
        session.flush()
        ListingHistoryRepository(session).ingest(ListingEventInput(
            instrument_id=instrument.id, source="fixture", source_contract_version="v1",
            source_record_key="listed", event_type="listed", effective_from=date(2010, 1, 1),
            market="KOSPI", evidence_state="observed", payload={},
        ), source_file_hash="a" * 64, observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        observation = PriceObservation(
            symbol_id=symbol.id, trade_date=date(2020, 1, 2), open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=10, change_rate=Decimal("0"),
            provider="kiwoom", adjustment_type="1", payload_hash="b" * 64,
            observed_at=datetime(2020, 1, 3, tzinfo=timezone.utc),
        )
        session.add(observation)
        second_observation = PriceObservation(
            symbol_id=symbol.id, trade_date=date(2020, 1, 3), open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"), volume=10, change_rate=Decimal("0"),
            provider="kiwoom", adjustment_type="1", payload_hash="c" * 64,
            observed_at=datetime(2020, 1, 4, tzinfo=timezone.utc),
        )
        session.add(second_observation)
        session.flush()
        selection = CleansingSelection(
            start=date(2020, 1, 2), end=date(2020, 1, 3), selection_as_of=date(2020, 1, 3),
            observation_cutoff=datetime(2020, 1, 4, tzinfo=timezone.utc),
        )
        first = create_clean_backtest_dataset(session, selection=selection, adjustment_policy="kiwoom:1")
        assert [(row.trade_date, row.quality_status) for row in first.memberships] == [
            (date(2020, 1, 2), "valid"), (date(2020, 1, 3), "valid")
        ]
        assert len(first.prices) == 2
        assert first.prices[0].source_observation_id == observation.id
        assert first.prices[0].close == Decimal("100")
        assert first.manifest["publication_scope"] == "complete_segments_only"
        assert first.manifest["coverage"]["valid"] == 2
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        page_one_response = Response()
        page_one = _materialized_dataset_page(
            request=request, response=page_one_response, session=session,
            dataset_id=first.dataset_id, start=selection.start, end=selection.end,
            markets=("KOSPI",), cursor=None, page_size=1, strict=False,
        )
        page_two_response = Response()
        page_two = _materialized_dataset_page(
            request=request, response=page_two_response, session=session,
            dataset_id=first.dataset_id, start=selection.start, end=selection.end,
            markets=("KOSPI",), cursor=page_one.next_cursor, page_size=1, strict=False,
        )
        assert [item.trade_date for item in page_one.items + page_two.items] == [date(2020, 1, 2), date(2020, 1, 3)]
        assert page_two.items[0].code == page_one.items[0].code
        assert page_one_response.headers["etag"] != page_two_response.headers["etag"]
        with pytest.raises(HTTPException) as changed_size:
            _materialized_dataset_page(
                request=request, response=Response(), session=session,
                dataset_id=first.dataset_id, start=selection.start, end=selection.end,
                markets=("KOSPI",), cursor=page_one.next_cursor, page_size=2, strict=False,
            )
        assert changed_size.value.status_code == 422
        session.commit()

        observation.close = Decimal("200")
        session.flush()
        second = create_clean_backtest_dataset(session, selection=selection, adjustment_policy="kiwoom:1")
        assert second.dataset_id != first.dataset_id
        assert first.prices[0].close == Decimal("100")

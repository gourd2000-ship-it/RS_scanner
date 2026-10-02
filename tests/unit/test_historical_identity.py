"""Regression coverage for BT02 historical instrument identity."""

from datetime import date
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.daily_price import DailyPrice
from app.models.symbol import Symbol
from app.repositories.instrument_repository import InstrumentRepository


def _repository() -> tuple[Session, InstrumentRepository]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, InstrumentRepository(session)


def test_reused_krx_code_creates_distinct_instruments_without_relinking_legacy_prices():
    session, repository = _repository()
    legacy_symbol = Symbol(code="123456", name="구 법인", market="KOSDAQ")
    session.add(legacy_symbol)
    session.flush()
    legacy_price = DailyPrice(
        symbol_id=legacy_symbol.id,
        trade_date=date(2010, 1, 4),
        open=100,
        high=110,
        low=90,
        close=105,
        volume=1000,
        change_rate=5,
    )
    session.add(legacy_price)
    session.flush()

    former = repository.create_instrument(
        krx_short_code="123456",
        isin="KR7000000001",
        name="구 법인",
        market="KOSDAQ",
        security_type="stock",
        listing_status="delisted",
        listed_at=date(2000, 1, 1),
        delisted_at=date(2011, 1, 1),
    )
    successor = repository.create_instrument(
        krx_short_code="123456",
        isin="KR7000000002",
        name="신 법인",
        market="KOSPI",
        security_type="stock",
        listing_status="listed",
        listed_at=date(2020, 1, 1),
    )

    assert former.id != successor.id
    assert [row.id for row in repository.find_by_krx_short_code("123456")] == [former.id, successor.id]
    assert session.get(DailyPrice, legacy_price.id).symbol_id == legacy_symbol.id


def test_provider_symbol_rejects_overlapping_reused_code_ranges_for_distinct_instruments():
    _session, repository = _repository()
    former = repository.create_instrument(
        krx_short_code="123456", isin="KR7000000001", name="구 법인", market="KOSDAQ",
        security_type="stock", listing_status="delisted",
    )
    successor = repository.create_instrument(
        krx_short_code="123456", isin="KR7000000002", name="신 법인", market="KOSPI",
        security_type="stock", listing_status="listed",
    )
    repository.add_provider_symbol(
        instrument_id=former.id,
        provider="kiwoom",
        provider_symbol="123456",
        mapping_status="matched",
        valid_from=date(2000, 1, 1),
        valid_to=date(2011, 1, 1),
    )

    with pytest.raises(ValueError, match="overlaps"):
        repository.add_provider_symbol(
            instrument_id=successor.id,
            provider="kiwoom",
            provider_symbol="123456",
            mapping_status="matched",
            valid_from=date(2010, 12, 31),
            valid_to=date(2021, 1, 1),
        )

    mapping = repository.add_provider_symbol(
        instrument_id=successor.id,
        provider="kiwoom",
        provider_symbol="123456",
        mapping_status="matched",
        valid_from=date(2020, 1, 1),
    )
    assert mapping.provider_symbol == "123456"


def test_provider_symbol_preserves_leading_zeroes_and_requires_a_valid_half_open_interval():
    _session, repository = _repository()
    instrument = repository.create_instrument(
        krx_short_code="005930", isin="KR7005930003", name="삼성전자", market="KOSPI",
        security_type="stock", listing_status="listed",
    )

    mapping = repository.add_provider_symbol(
        instrument_id=instrument.id,
        provider="kiwoom",
        provider_symbol="005930A",
        mapping_status="matched",
        valid_from=date(2020, 1, 1),
        valid_to=date(2021, 1, 1),
    )

    assert mapping.provider_symbol == "005930A"
    with pytest.raises(ValueError, match="valid_to must be later"):
        repository.add_provider_symbol(
            instrument_id=instrument.id,
            provider="kiwoom",
            provider_symbol="005930A",
            mapping_status="matched",
            valid_from=date(2021, 1, 1),
            valid_to=date(2021, 1, 1),
        )


def test_identity_migration_removes_only_the_reused_code_constraint_and_keeps_legacy_price_owner_tables():
    migration_path = Path(__file__).parents[2] / "alembic/versions/h2b3c4d5e6f7_historical_instrument_identity.py"
    spec = importlib.util.spec_from_file_location("historical_identity_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_unique_constraints.return_value = [{"name": "uq_instruments_krx_short_code"}]
    inspector.get_indexes.return_value = []
    drop_constraint = Mock()
    create_index = Mock()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=object()), raising=False)
    monkeypatch.setattr(migration.sa, "inspect", Mock(return_value=inspector))
    monkeypatch.setattr(migration.op, "drop_constraint", drop_constraint)
    monkeypatch.setattr(migration.op, "create_index", create_index)
    try:
        migration.upgrade()
    finally:
        monkeypatch.undo()

    drop_constraint.assert_called_once_with("uq_instruments_krx_short_code", "instruments", type_="unique")
    create_index.assert_called_once_with("ix_instruments_krx_short_code", "instruments", ["krx_short_code"])

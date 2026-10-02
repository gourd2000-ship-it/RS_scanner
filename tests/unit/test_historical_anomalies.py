"""BT08 policies explain historical outliers without silently excluding them."""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import CorporateAction, OhlcExclusion
from app.models.symbol import Symbol
from app.schemas.market_data import DailyPricePayload
from app.services.validation.historical_policy import HistoricalValidationPolicy, validate_historical_prices


def _row(day: str, close: str, *, volume: int = 100, change_rate: str = "0", low: str | None = None) -> DailyPricePayload:
    value = Decimal(close)
    return DailyPricePayload(
        trade_date=date.fromisoformat(day), open=value, high=value, low=Decimal(low) if low else value,
        close=value, volume=volume, change_rate=Decimal(change_rate),
    )


def _session() -> tuple[Session, Symbol]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    symbol = Symbol(code="000001", name="표본", market="KOSPI")
    session.add(symbol)
    session.flush()
    return session, symbol


def test_corporate_action_and_liquidation_evidence_explain_extreme_return_without_auto_exclusion():
    session, symbol = _session()
    session.add(CorporateAction(symbol_id=symbol.id, event_date=date(2020, 1, 3), event_type="reverse_split", source="kind"))
    result = validate_historical_prices(
        session, symbol_id=symbol.id,
        rows=[_row("2020-01-02", "100"), _row("2020-01-03", "1000", volume=0, change_rate="900")],
        trading_status_by_date={date(2020, 1, 3): "liquidation_trading"},
        policy=HistoricalValidationPolicy(version="historic-v1"),
    )

    assert {case.reason_code for case in result.cases} >= {"CORPORATE_ACTION_EXPLAINED", "LIQUIDATION_EXCEPTION"}
    assert session.scalars(select(OhlcExclusion)).all() == []


def test_bad_ohlc_creates_a_replayable_case_and_proposed_exclusion_but_does_not_mutate_price():
    session, symbol = _session()
    result = validate_historical_prices(
        session, symbol_id=symbol.id,
        rows=[_row("2020-01-02", "100", low="101")],
        policy=HistoricalValidationPolicy(version="historic-v1"),
    )

    assert result.cases[0].reason_code == "INVALID_OHLC"
    exclusion = session.scalars(select(OhlcExclusion)).one()
    assert (exclusion.status, exclusion.reason_code) == ("PROPOSED", "INVALID_OHLC")
    assert result.replay_hash


def test_provider_sign_convention_is_a_warning_not_an_automatic_correction_or_exclusion():
    session, symbol = _session()
    result = validate_historical_prices(
        session, symbol_id=symbol.id,
        rows=[_row("2020-01-02", "100"), _row("2020-01-03", "200", change_rate="-100")],
        policy=HistoricalValidationPolicy(version="historic-v1"),
    )

    sign_case = next(case for case in result.cases if case.reason_code == "PROVIDER_SIGN_CONVENTION")
    assert sign_case.severity == "warning"
    assert session.scalars(select(OhlcExclusion)).all() == []


def test_same_rows_and_policy_replay_to_the_same_historical_decisions():
    session, symbol = _session()
    rows = [_row("2020-01-02", "100"), _row("2020-01-03", "200", change_rate="100")]
    policy = HistoricalValidationPolicy(version="historic-v1")

    first = validate_historical_prices(session, symbol_id=symbol.id, rows=rows, policy=policy)
    second = validate_historical_prices(session, symbol_id=symbol.id, rows=rows, policy=policy)

    assert first.replay_hash == second.replay_hash


def test_merger_and_dividend_evidence_are_separate_valid_explanations_for_large_historical_returns():
    session, symbol = _session()
    for event_day, event_type in ((date(2020, 1, 3), "merger"), (date(2020, 1, 5), "dividend")):
        session.add(CorporateAction(symbol_id=symbol.id, event_date=event_day, event_type=event_type, source="kind"))
    rows = [
        _row("2020-01-02", "100"), _row("2020-01-03", "200", change_rate="100"),
        _row("2020-01-04", "200"), _row("2020-01-05", "100", change_rate="-50"),
    ]

    result = validate_historical_prices(
        session, symbol_id=symbol.id, rows=rows, policy=HistoricalValidationPolicy(version="historic-v1")
    )

    explained = [case.evidence["event_type"] for case in result.cases if case.reason_code == "CORPORATE_ACTION_EXPLAINED"]
    assert explained == ["merger", "dividend"]

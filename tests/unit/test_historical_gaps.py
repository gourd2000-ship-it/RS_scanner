"""BT07 historical coverage must explain zero-price targets, not hide them."""

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.base import Base
from app.models.data_quality import ValidationCase
from app.models.instrument import Instrument
from app.models.symbol import Symbol

from app.services.historical_universe import (
    HistoricalUniverseEntry,
    HistoricalUniverseManifest,
    HistoricalUniverseRequest,
)
from app.services.validation.historical_gaps import (
    BackfillOutcome,
    assess_historical_gaps,
    persist_historical_gap_result,
)


def _manifest() -> HistoricalUniverseManifest:
    request = HistoricalUniverseRequest(start=date(2020, 1, 2), end=date(2020, 1, 6))
    return HistoricalUniverseManifest(
        request=request,
        entries=(
            HistoricalUniverseEntry(date(2020, 1, 2), 1, "KOSPI", "stock", "observed", "trading", "expected"),
            HistoricalUniverseEntry(date(2020, 1, 3), 1, "KOSPI", "stock", "observed", "trading", "expected"),
            # A delisted name can have no price at all and must still be a case.
            HistoricalUniverseEntry(date(2020, 1, 2), 2, "KOSDAQ", "stock", "observed", "trading", "expected"),
            HistoricalUniverseEntry(date(2020, 1, 3), 2, "KOSDAQ", "stock", "observed", "suspended", "outside_trading_interval"),
            HistoricalUniverseEntry(date(2020, 1, 6), 3, "KOSPI", "stock", "observed", "trading", "expected"),
        ),
        expected_price_count=4,
        membership_completeness=None,
        unknown_instrument_ids=(9,),
        excluded_instrument_counts={},
    )


def test_gap_cases_distinguish_expected_missing_suspension_fetch_failure_and_preparation_shortage():
    result = assess_historical_gaps(
        _manifest(),
        observed_dates={(1, date(2020, 1, 2))},
        valid_dates={(1, date(2020, 1, 2))},
        outcomes={
            2: BackfillOutcome(reason="fetch_failed", evidence={"http_status": 503}),
            3: BackfillOutcome(reason="preparation_history_insufficient", evidence={"available_rows": 2}),
        },
        delisted_instrument_ids={2},
        is_trading_day=lambda day: day.weekday() < 5,
    )

    assert {(case.instrument_id, case.reason_code) for case in result.cases} == {
        (1, "expected_missing"),
        (2, "fetch_failed"),
        (2, "confirmed_suspension"),
        (3, "preparation_history_insufficient"),
    }
    missing = next(case for case in result.cases if case.instrument_id == 1)
    assert missing.evidence["range"] == ["2020-01-03", "2020-01-03"]
    fetch = next(case for case in result.cases if case.instrument_id == 2 and case.reason_code == "fetch_failed")
    assert fetch.evidence["http_status"] == 503


def test_coverage_keeps_unknown_membership_denominator_unknown_and_groups_delisted_market_year():
    result = assess_historical_gaps(
        _manifest(),
        observed_dates={(1, date(2020, 1, 2))},
        valid_dates={(1, date(2020, 1, 2))},
        delisted_instrument_ids={2},
        is_trading_day=lambda day: day.weekday() < 5,
    )

    kosdaq_delisted = next(row for row in result.coverage if row.market == "KOSDAQ")
    assert (kosdaq_delisted.year, kosdaq_delisted.delisted, kosdaq_delisted.price_denominator) == (2020, True, 1)
    assert kosdaq_delisted.price_numerator == 0
    assert kosdaq_delisted.membership_denominator is None
    assert result.excluded_date_reasons["holiday_or_non_trading"] == 2  # weekend Jan 4/5


def test_gap_cases_are_persisted_with_their_range_evidence_and_validator_version():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        instrument = Instrument(krx_short_code="000001", isin="KR7000000001", name="표본", market="KOSPI", security_type="stock")
        session.add(instrument)
        session.flush()
        session.add(Symbol(code="000001", name="표본", market="KOSPI", instrument_id=instrument.id))
        session.flush()
        result = assess_historical_gaps(
            _manifest(), observed_dates={(1, date(2020, 1, 2))}, valid_dates={(1, date(2020, 1, 2))},
            is_trading_day=lambda day: day.weekday() < 5,
        )
        run_id = persist_historical_gap_result(session, result)
        persisted = list(session.scalars(select(ValidationCase).where(ValidationCase.validation_run_id == run_id)))

    missing = next(case for case in persisted if case.reason_code == "expected_missing")
    assert missing.validator_version == "historical-gaps-v1"
    assert missing.evidence["range"] == ["2020-01-03", "2020-01-03"]

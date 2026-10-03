from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json

import pytest

from app.services.indicators import (
    EMA_PERIODS,
    INPUT_POLICY_VERSION,
    EmaInputRow,
    EmaInputStatus,
    EmaSourcePolicy,
    EmaStatus,
    IdentitySnapshot,
    InputReasonCode,
    compare_input_histories,
    compute_ema,
    input_row_fingerprint,
    result_hash,
    select_latest_input,
)


_POLICY = EmaSourcePolicy(
    provider="kiwoom", adjustment_type="1", allowed_parser_versions=("kiwoom-v2",),
    observation_cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
)


def _row(
    day: int,
    close: str | None,
    *,
    status: EmaInputStatus = EmaInputStatus.ELIGIBLE,
    reason: InputReasonCode | None = None,
    provider: str = "kiwoom",
    adjustment_type: str = "1",
) -> EmaInputRow:
    trade_date = date(2024, 1, 1) + timedelta(days=day - 1)
    observed_at = datetime(2024, 1, 1, 9, tzinfo=timezone.utc) + timedelta(days=day - 1)
    identity = IdentitySnapshot(
        snapshot_id=day,
        instrument_id=101,
        provider="kiwoom",
        provider_symbol="005930",
        provider_mapping_id=501,
        mapping_status="matched",
        valid_from=date(2020, 1, 1),
        valid_to=None,
        resolver_version="provider-symbol-resolver-v1",
        resolved_at=observed_at,
    )
    return EmaInputRow(
        trade_date=trade_date,
        instrument_id=101,
        symbol_id=201,
        observation_id=day,
        identity=identity,
        provider=provider,
        provider_symbol="005930",
        adjustment_type=adjustment_type,
        parser_version="kiwoom-v2",
        close=Decimal(close) if close is not None else None,
        volume=1000,
        observed_at=observed_at,
        payload_hash=f"{day:064x}",
        input_status=status,
        reason_code=reason,
        source_policy=_POLICY,
    )


def _values(result, period: int):
    return [value for value in result.values if value.period == period]


@pytest.mark.parametrize("period", EMA_PERIODS)
def test_first_eligible_close_seeds_each_period_and_nth_is_available(period: int):
    result = compute_ema([_row(day, str(100 + day)) for day in range(1, period + 1)])
    values = _values(result, period)

    assert values[0].value == Decimal("101")
    assert values[period - 2].status is EmaStatus.WARMING_UP
    assert values[period - 1].status is EmaStatus.AVAILABLE
    assert values[period - 1].available_observations == period
    assert all(value.reason_code is InputReasonCode.WARMING_UP for value in values[:-1])


def test_ema_uses_unrounded_decimal_state_for_rising_and_falling_closes():
    rising_then_falling = [_row(1, "10"), _row(2, "11"), _row(3, "12"), _row(4, "11"), _row(5, "10")]
    result = compute_ema(rising_then_falling)
    ema5 = _values(result, 5)

    with localcontext() as context:
        context.prec = 50
        expected_second = Decimal("10") + Decimal(2) / Decimal(6)
        expected_third = Decimal(2) / Decimal(6) * Decimal("12") + (Decimal(1) - Decimal(2) / Decimal(6)) * expected_second
        rounded_state = expected_second.quantize(Decimal("0.1"))
        rounded_third = Decimal(2) / Decimal(6) * Decimal("12") + (Decimal(1) - Decimal(2) / Decimal(6)) * rounded_state
    assert ema5[1].value == expected_second
    assert ema5[2].value == expected_third
    assert ema5[-1].value < ema5[-2].value

    assert ema5[2].value != rounded_third


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (EmaInputStatus.MISSING, InputReasonCode.MISSING_SELECTED_SOURCE),
        (EmaInputStatus.INVALID, InputReasonCode.INVALID_OHLCV),
        (EmaInputStatus.REVIEW_REQUIRED, InputReasonCode.OPEN_VALIDATION_CASE),
        (EmaInputStatus.ELIGIBLE, InputReasonCode.IDENTITY_UNAVAILABLE),
    ],
)
def test_non_eligible_input_breaks_series_without_carrying_value(status, reason):
    result = compute_ema([_row(1, "100"), _row(2, None, status=status, reason=reason), _row(3, "102")])

    for period in EMA_PERIODS:
        values = _values(result, period)
        assert values[1].status is EmaStatus.DATA_UNAVAILABLE
        assert values[1].reason_code is reason
        assert values[1].value is None
        assert values[2].status is EmaStatus.DATA_UNAVAILABLE
        assert values[2].reason_code is reason
        assert values[2].value is None
        assert values[2].available_observations == 0


def test_confirmed_trading_halt_does_not_count_or_break_the_series():
    result = compute_ema([
        _row(1, "100"),
        _row(2, None, status=EmaInputStatus.CONFIRMED_TRADING_HALT,
             reason=InputReasonCode.CONFIRMED_TRADING_HALT),
        _row(3, "102"),
    ])
    ema5 = _values(result, 5)

    assert ema5[1].status is EmaStatus.DATA_UNAVAILABLE
    assert ema5[1].reason_code is InputReasonCode.CONFIRMED_TRADING_HALT
    assert ema5[2].status is EmaStatus.WARMING_UP
    assert ema5[2].available_observations == 2
    with localcontext() as context:
        context.prec = 50
        expected = Decimal(2) / Decimal(6) * Decimal("102") + Decimal(4) / Decimal(6) * Decimal("100")
    assert ema5[2].value == expected


def test_provider_or_adjustment_discontinuity_breaks_the_series():
    result = compute_ema([_row(1, "100"), _row(2, "101", adjustment_type="2"), _row(3, "102")])

    for period in EMA_PERIODS:
        values = _values(result, period)
        assert values[1].reason_code is InputReasonCode.PROVIDER_OR_ADJUSTMENT_DISCONTINUITY
        assert values[2].reason_code is InputReasonCode.PROVIDER_OR_ADJUSTMENT_DISCONTINUITY


def test_source_policy_uses_utc_cutoff_and_last_observation_tiebreak():
    policy = EmaSourcePolicy(
        provider="kiwoom", adjustment_type="1", allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )
    earlier = _row(1, "100")
    later = _row(2, "101")
    after_cutoff = _row(4, "103")

    assert select_latest_input([earlier, after_cutoff, later], policy) == later
    assert _row(1, "100", provider="naver").effective_reason(policy) is InputReasonCode.IDENTITY_UNAVAILABLE


def test_identity_snapshot_is_required_and_current_symbol_is_not_an_input():
    row = _row(1, "100")
    unavailable = EmaInputRow(**{**row.__dict__, "identity": None})
    result = compute_ema([unavailable])

    assert all(value.status is EmaStatus.DATA_UNAVAILABLE for value in result.values)
    assert all(value.reason_code is InputReasonCode.IDENTITY_UNAVAILABLE for value in result.values)


def test_identity_mapping_valid_to_is_an_exclusive_bound():
    row = _row(2, "100")
    ending_that_day = IdentitySnapshot(**{**row.identity.__dict__, "valid_to": row.trade_date})
    result = compute_ema([EmaInputRow(**{**row.__dict__, "identity": ending_that_day})])

    assert all(value.status is EmaStatus.DATA_UNAVAILABLE for value in result.values)
    assert all(value.reason_code is InputReasonCode.IDENTITY_UNAVAILABLE for value in result.values)


def test_input_enums_are_normalized_and_unknown_values_are_rejected():
    normalized = _row(1, "100", status="eligible", reason="identity_unavailable")

    assert normalized.input_status is EmaInputStatus.ELIGIBLE
    assert normalized.reason_code is InputReasonCode.IDENTITY_UNAVAILABLE
    assert normalized.fingerprint_material()["reason_code"] is InputReasonCode.IDENTITY_UNAVAILABLE
    with pytest.raises(ValueError, match="unsupported EMA input status"):
        _row(1, "100", status="not-a-status")
    with pytest.raises(ValueError, match="unsupported EMA input reason code"):
        _row(1, "100", reason="not-a-reason")


def test_missing_source_policy_or_observation_time_is_data_unavailable_without_type_error():
    row = _row(1, "100")
    no_policy = EmaInputRow(**{**row.__dict__, "source_policy": None})
    no_observed_at = EmaInputRow(**{**row.__dict__, "observed_at": None})
    past_cutoff = EmaSourcePolicy(
        provider="kiwoom", adjustment_type="1", allowed_parser_versions=("kiwoom-v2",),
        observation_cutoff=datetime(2023, 12, 31, tzinfo=timezone.utc),
    )
    after_cutoff = EmaInputRow(**{**row.__dict__, "source_policy": past_cutoff})

    for candidate in (no_policy, no_observed_at, after_cutoff):
        result = compute_ema([candidate])
        assert all(value.status is EmaStatus.DATA_UNAVAILABLE for value in result.values)
        assert all(value.reason_code is InputReasonCode.MISSING_SELECTED_SOURCE for value in result.values)


def test_fingerprint_and_result_hash_are_canonical_and_deterministic():
    row = _row(1, "100.00")
    same_value_different_decimal_spelling = _row(1, "100.0")

    assert input_row_fingerprint(row) == input_row_fingerprint(same_value_different_decimal_spelling)
    first = compute_ema([row, _row(2, "101")])
    second = compute_ema([same_value_different_decimal_spelling, _row(2, "101.0")])
    assert first.input_hash == second.input_hash
    assert result_hash(first.values) == result_hash(second.values)

    precise = _row(1, "100.123456789012345678901234567890")
    with localcontext() as context:
        context.prec = 7
        low_context_fingerprint = input_row_fingerprint(precise)
    assert low_context_fingerprint == input_row_fingerprint(precise)


def test_prefix_extension_is_distinguished_from_a_revision_and_fixture_is_stable():
    fixture = json.loads((__import__("pathlib").Path(__file__).parents[1] / "fixtures/ema/input_rows.json").read_text())
    base = [_row(row["day"], row["close"]) for row in fixture["base"]]
    extended = [*base, _row(fixture["extension"]["day"], fixture["extension"]["close"])]
    revised = [*base]
    revised[1] = _row(2, "999")

    assert compare_input_histories(base, extended).kind == "prefix_extended"
    comparison = compare_input_histories(base, revised)
    assert comparison.kind == "rebuild_required"
    assert comparison.first_changed_index == 1


def test_rejects_out_of_order_or_duplicate_trading_dates():
    with pytest.raises(ValueError, match="strictly increasing"):
        compute_ema([_row(2, "101"), _row(1, "100")])
    with pytest.raises(ValueError, match="strictly increasing"):
        compute_ema([_row(1, "100"), _row(1, "100")])


def test_policy_version_is_fixed_in_fingerprint_material():
    material = _row(1, "100").fingerprint_material()
    assert material["input_policy_version"] == INPUT_POLICY_VERSION

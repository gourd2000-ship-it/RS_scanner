"""순수 Decimal EMA 계산기."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Iterable

from app.services.indicators.contracts import (
    EMA_PERIODS,
    EmaCalculationResult,
    EmaInputRow,
    EmaInputStatus,
    EmaStatus,
    EmaValue,
    InputReasonCode,
    build_prefix_hashes,
    result_hash,
)


# DB numeric scale나 표시 자릿수가 다음 계산값에 영향을 주지 않도록 충분히 높은 고정 정밀도를 쓴다.
EMA_DECIMAL_PRECISION = 50


def compute_ema(rows: Iterable[EmaInputRow]) -> EmaCalculationResult:
    """EMA 5·20·50·200을 한 번 순회해 계산한다.

    적격 종가가 끊기면 그 행과 이후 행은 현재 generation에서 ``data_unavailable``이다.
    ``confirmed_trading_halt``는 가격이 없는 근거 있는 거래일 표지이므로 값은 만들지 않고
    연속 적격 관측 수나 직전 내부 EMA 상태를 끊지 않는다.
    """
    inputs = tuple(rows)
    _validate_order(inputs)
    fingerprints, prefixes = build_prefix_hashes(inputs)
    values: list[EmaValue] = []
    states = {period: _PeriodState() for period in EMA_PERIODS}
    continuity: tuple[str, str | None] | None = None

    with localcontext() as context:
        context.prec = EMA_DECIMAL_PRECISION
        for row, prefix in zip(inputs, prefixes, strict=True):
            reason = row.effective_reason()
            if reason is None:
                current_source = (row.provider, row.adjustment_type)
                if continuity is None:
                    continuity = current_source
                elif current_source != continuity:
                    reason = InputReasonCode.PROVIDER_OR_ADJUSTMENT_DISCONTINUITY
            if reason is InputReasonCode.CONFIRMED_TRADING_HALT:
                for period, state in states.items():
                    values.append(EmaValue(
                        trade_date=row.trade_date, period=period, value=None,
                        status=EmaStatus.DATA_UNAVAILABLE, reason_code=reason,
                        available_observations=state.observations, input_prefix_hash=prefix,
                    ))
                continue

            if reason is not None:
                for state in states.values():
                    state.break_reason = reason
                    state.value = None
                    state.observations = 0
                for period in EMA_PERIODS:
                    values.append(EmaValue(
                        trade_date=row.trade_date, period=period, value=None,
                        status=EmaStatus.DATA_UNAVAILABLE, reason_code=reason,
                        available_observations=0, input_prefix_hash=prefix,
                    ))
                continue

            for period, state in states.items():
                if state.break_reason is not None:
                    values.append(EmaValue(
                        trade_date=row.trade_date, period=period, value=None,
                        status=EmaStatus.DATA_UNAVAILABLE, reason_code=state.break_reason,
                        available_observations=0, input_prefix_hash=prefix,
                    ))
                    continue
                state.observations += 1
                if state.value is None:
                    state.value = row.close
                else:
                    alpha = Decimal(2) / Decimal(period + 1)
                    state.value = alpha * row.close + (Decimal(1) - alpha) * state.value
                status = EmaStatus.AVAILABLE if state.observations >= period else EmaStatus.WARMING_UP
                values.append(EmaValue(
                    trade_date=row.trade_date, period=period, value=state.value, status=status,
                    reason_code=None if status is EmaStatus.AVAILABLE else InputReasonCode.WARMING_UP,
                    available_observations=state.observations, input_prefix_hash=prefix,
                ))

    output = tuple(values)
    return EmaCalculationResult(
        values=output,
        row_fingerprints=fingerprints,
        prefix_hashes=prefixes,
        input_hash=prefixes[-1] if prefixes else _empty_input_hash(),
        result_hash=result_hash(output),
    )


class _PeriodState:
    def __init__(self) -> None:
        self.value: Decimal | None = None
        self.observations = 0
        self.break_reason: InputReasonCode | None = None


def _validate_order(rows: tuple[EmaInputRow, ...]) -> None:
    for previous, current in zip(rows, rows[1:], strict=False):
        if current.trade_date <= previous.trade_date:
            raise ValueError("EMA input trade dates must be strictly increasing")


def _empty_input_hash() -> str:
    from app.services.indicators.contracts import canonical_json
    from hashlib import sha256

    return sha256(canonical_json([]).encode("utf-8")).hexdigest()

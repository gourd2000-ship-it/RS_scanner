"""EMA 입력과 결과의 DB-독립 계약.

이 모듈은 현재 ``DailyPrice``나 ``Symbol``을 읽지 않는다. DB selector와 저장소는
후속 작업에서 이 불변 값 객체를 만들어 전달하며, 계산기는 그 snapshot만 신뢰한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable


INPUT_POLICY_VERSION = "validated-observation-close-v3"
EMA_PERIODS = (5, 20, 50, 200)
EMA_FORMULA_VERSION = "ema-close-seed-v1"


class InputReasonCode(str, Enum):
    """EMA 입력과 조회 행에서 허용하는 사유 코드 전체."""

    WARMING_UP = "warming_up"
    MISSING_SELECTED_SOURCE = "missing_selected_source"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    AMBIGUOUS_IDENTITY_MAPPING = "ambiguous_identity_mapping"
    CONFLICTING_OBSERVATIONS = "conflicting_observations"
    APPROVED_EXCLUSION = "approved_exclusion"
    APPROVED_VALIDATION_EXCLUSION = "approved_validation_exclusion"
    OPEN_VALIDATION_CASE = "open_validation_case"
    INVALID_APPROVED_CORRECTION = "invalid_approved_correction"
    INVALID_OHLCV = "invalid_ohlcv"
    PROVIDER_OR_ADJUSTMENT_DISCONTINUITY = "provider_or_adjustment_discontinuity"
    CONFIRMED_TRADING_HALT = "confirmed_trading_halt"


class EmaInputStatus(str, Enum):
    """Selector가 snapshot에 확정해 전달하는 입력 판정."""

    ELIGIBLE = "eligible"
    MISSING = "missing"
    INVALID = "invalid"
    REVIEW_REQUIRED = "review_required"
    CONFIRMED_TRADING_HALT = "confirmed_trading_halt"


class EmaStatus(str, Enum):
    WARMING_UP = "warming_up"
    AVAILABLE = "available"
    DATA_UNAVAILABLE = "data_unavailable"


class InputHistoryKind(str, Enum):
    UNCHANGED = "unchanged"
    PREFIX_EXTENDED = "prefix_extended"
    REBUILD_REQUIRED = "rebuild_required"


@dataclass(frozen=True)
class IdentitySnapshot:
    """관측 당시 확정한 ProviderSymbol → Instrument 근거의 사본.

    ``snapshot_id``는 T2가 만드는 append-only 행의 식별자다. 이 계약에서는 DB 모델이
    아직 없으므로 ID와 증거 필드를 함께 보관한다. 현재 Symbol/Instrument의 연결은 이
    값을 보완하거나 대체할 수 없다.
    """

    snapshot_id: int | None
    instrument_id: int | None
    provider: str
    provider_symbol: str | None
    provider_mapping_id: int | None
    mapping_status: str | None
    valid_from: date | None
    valid_to: date | None
    resolver_version: str | None
    resolved_at: datetime | None

    def proves(self, *, instrument_id: int, provider: str, provider_symbol: str, trade_date: date) -> InputReasonCode | None:
        """해당 거래일의 정확히 하나인 matched mapping을 증명하는지 판단한다."""
        if self.snapshot_id is None:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        if self.mapping_status == "ambiguous":
            return InputReasonCode.AMBIGUOUS_IDENTITY_MAPPING
        if self.mapping_status != "matched":
            return InputReasonCode.IDENTITY_UNAVAILABLE
        if self.instrument_id is None or self.provider_mapping_id is None:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        if self.instrument_id != instrument_id or self.provider != provider or self.provider_symbol != provider_symbol:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        if self.valid_from is not None and trade_date < self.valid_from:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        # ProviderSymbol validity is [valid_from, valid_to): the date at valid_to
        # belongs to a later mapping and must never be attributed to this one.
        if self.valid_to is not None and trade_date >= self.valid_to:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        return None

    def fingerprint_material(self) -> dict[str, Any]:
        return {
            "identity_snapshot_id": self.snapshot_id,
            "identity_instrument_id": self.instrument_id,
            "identity_provider": self.provider,
            "identity_provider_symbol": self.provider_symbol,
            "provider_mapping_id": self.provider_mapping_id,
            "mapping_status": self.mapping_status,
            "mapping_valid_from": self.valid_from,
            "mapping_valid_to": self.valid_to,
            "resolver_version": self.resolver_version,
            "identity_resolved_at": self.resolved_at,
        }


@dataclass(frozen=True)
class ValidationCaseEvidence:
    """선택 시점에 적용된 validation case의 재현 가능한 축약 근거."""

    case_id: int
    case_status: str
    decision: str | None

    def fingerprint_material(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "case_status": self.case_status, "decision": self.decision}


@dataclass(frozen=True)
class EmaSourcePolicy:
    """series 생성 시 고정하는 입력 선택 정책 snapshot."""

    provider: str
    adjustment_type: str
    allowed_parser_versions: tuple[str, ...]
    observation_cutoff: datetime
    version: str = INPUT_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != INPUT_POLICY_VERSION:
            raise ValueError(f"unsupported input policy version: {self.version}")
        if not self.provider or not self.adjustment_type:
            raise ValueError("provider and adjustment_type are required")
        if not self.allowed_parser_versions:
            raise ValueError("allowed_parser_versions must not be empty")
        if self.observation_cutoff.tzinfo is None or self.observation_cutoff.utcoffset() is None:
            raise ValueError("observation_cutoff must be timezone-aware UTC")
        if self.observation_cutoff.utcoffset().total_seconds() != 0:
            raise ValueError("observation_cutoff must be UTC")

    def accepts(self, row: EmaInputRow) -> bool:
        return (
            row.provider == self.provider
            and row.adjustment_type == self.adjustment_type
            and row.parser_version in self.allowed_parser_versions
            and row.observed_at is not None
            and row.observed_at <= self.observation_cutoff
        )

    def fingerprint_material(self) -> dict[str, Any]:
        """정책 변경을 재계산 판단에 포함하기 위한 명시적 material."""
        return {
            "version": self.version,
            "provider": self.provider,
            "adjustment_type": self.adjustment_type,
            "allowed_parser_versions": tuple(sorted(self.allowed_parser_versions)),
            "observation_cutoff": self.observation_cutoff,
        }


@dataclass(frozen=True)
class CloseCorrectionEvidence:
    """승인된 close 보정. selector는 id가 가장 큰 유효 보정을 적용한다."""

    correction_id: int
    value: Decimal | None
    status: str


@dataclass(frozen=True)
class EmaInputRow:
    """EMA 한 거래일 입력의 불변 snapshot.

    ``fingerprint_material``의 키가 SHA-256에 들어가는 전체 필드 목록이다. 원본
    PriceObservation과 나중에 생길 DB identity snapshot은 참조하지 않고 이 복사본으로
    재현한다.
    """

    trade_date: date
    instrument_id: int
    symbol_id: int | None
    observation_id: int | None
    identity: IdentitySnapshot | None
    provider: str
    provider_symbol: str
    adjustment_type: str | None
    parser_version: str | None
    close: Decimal | None
    volume: int | None
    observed_at: datetime | None
    payload_hash: str | None
    correction_ids: tuple[int, ...] = ()
    validation_cases: tuple[ValidationCaseEvidence, ...] = ()
    input_status: EmaInputStatus = EmaInputStatus.ELIGIBLE
    reason_code: InputReasonCode | None = None
    input_policy_version: str = INPUT_POLICY_VERSION
    source_policy: EmaSourcePolicy | None = None
    # Shared OHLC evidence only: legacy close-v3 fingerprints remain unchanged.
    high: Decimal | None = None
    low: Decimal | None = None

    def __post_init__(self) -> None:
        try:
            normalized_status = EmaInputStatus(self.input_status)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported EMA input status: {self.input_status!r}") from exc
        object.__setattr__(self, "input_status", normalized_status)
        if self.reason_code is not None:
            try:
                normalized_reason = InputReasonCode(self.reason_code)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported EMA input reason code: {self.reason_code!r}") from exc
            object.__setattr__(self, "reason_code", normalized_reason)
        if self.input_policy_version != INPUT_POLICY_VERSION:
            raise ValueError(f"unsupported input policy version: {self.input_policy_version}")
        if self.observed_at is not None and (self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None):
            raise ValueError("observed_at must be timezone-aware")
        if self.reason_code is InputReasonCode.WARMING_UP:
            raise ValueError("warming_up is a calculation result, not input evidence")

    def effective_reason(self, source_policy: EmaSourcePolicy | None = None) -> InputReasonCode | None:
        """계산기가 신뢰할 입력 판정을 반환한다. 명시적 selector 판정이 우선한다."""
        if self.input_status is EmaInputStatus.CONFIRMED_TRADING_HALT:
            return InputReasonCode.CONFIRMED_TRADING_HALT
        if self.reason_code is not None:
            return self.reason_code
        if self.input_status is not EmaInputStatus.ELIGIBLE:
            return InputReasonCode.MISSING_SELECTED_SOURCE
        effective_policy = source_policy or self.source_policy
        # A selected observation is meaningful only under the source policy and
        # cutoff that selected it. Missing evidence is unavailable, never an
        # implicit "accept all" policy.
        if effective_policy is None or self.observed_at is None:
            return InputReasonCode.MISSING_SELECTED_SOURCE
        if self.identity is None:
            return InputReasonCode.IDENTITY_UNAVAILABLE
        identity_reason = self.identity.proves(
            instrument_id=self.instrument_id,
            provider=self.provider,
            provider_symbol=self.provider_symbol,
            trade_date=self.trade_date,
        )
        if identity_reason is not None:
            return identity_reason
        if self.observed_at > effective_policy.observation_cutoff:
            return InputReasonCode.MISSING_SELECTED_SOURCE
        if not effective_policy.accepts(self):
            return InputReasonCode.PROVIDER_OR_ADJUSTMENT_DISCONTINUITY
        if self.close is None or not self.close.is_finite() or self.close <= 0 or self.volume is None or self.volume < 0:
            return InputReasonCode.INVALID_OHLCV
        return None

    def fingerprint_material(self) -> dict[str, Any]:
        """입력 행 hash에 포함하는 명시적, 순수-data material."""
        identity = self.identity.fingerprint_material() if self.identity is not None else {
            "identity_snapshot_id": None,
            "identity_instrument_id": None,
            "identity_provider": None,
            "identity_provider_symbol": None,
            "provider_mapping_id": None,
            "mapping_status": None,
            "mapping_valid_from": None,
            "mapping_valid_to": None,
            "resolver_version": None,
            "identity_resolved_at": None,
        }
        return {
            "input_policy_version": self.input_policy_version,
            "source_policy": self.source_policy.fingerprint_material() if self.source_policy is not None else None,
            "trade_date": self.trade_date,
            "instrument_id": self.instrument_id,
            "symbol_id": self.symbol_id,
            "selected_observation_id": self.observation_id,
            **identity,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "adjustment_type": self.adjustment_type,
            "parser_version": self.parser_version,
            "close": self.close,
            "volume": self.volume,
            "observed_at": self.observed_at,
            "payload_hash": self.payload_hash,
            "correction_ids": tuple(sorted(self.correction_ids)),
            "validation_cases": tuple(
                case.fingerprint_material() for case in sorted(self.validation_cases, key=lambda item: item.case_id)
            ),
            "input_status": self.input_status,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class EmaValue:
    trade_date: date
    period: int
    value: Decimal | None
    status: EmaStatus
    reason_code: InputReasonCode | None
    available_observations: int
    input_prefix_hash: str

    def result_material(self) -> dict[str, Any]:
        """결과 hash에 포함하는 명시적 필드."""
        return {
            "period": self.period,
            "trade_date": self.trade_date,
            "status": self.status,
            "value": self.value,
            "reason_code": self.reason_code,
            "available_observations": self.available_observations,
            "input_prefix_hash": self.input_prefix_hash,
        }


@dataclass(frozen=True)
class EmaCalculationResult:
    values: tuple[EmaValue, ...]
    row_fingerprints: tuple[str, ...]
    prefix_hashes: tuple[str, ...]
    input_hash: str
    result_hash: str


@dataclass(frozen=True)
class InputHistoryComparison:
    kind: InputHistoryKind
    first_changed_index: int | None
    previous_count: int
    current_count: int


def canonical_json(value: Any) -> str:
    """날짜·UTC 시각·Decimal·enum을 고정 표현으로 만드는 canonical JSON."""
    return json.dumps(_canonicalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def input_row_fingerprint(row: EmaInputRow) -> str:
    return _hash_material(row.fingerprint_material())


def prefix_hash(previous_prefix_hash: str | None, row_fingerprint: str) -> str:
    """이전 prefix와 현재 immutable row fingerprint만으로 다음 prefix를 만든다."""
    return _hash_material({"previous_prefix_hash": previous_prefix_hash, "row_fingerprint": row_fingerprint})


def build_prefix_hashes(rows: Iterable[EmaInputRow]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    fingerprints = tuple(input_row_fingerprint(row) for row in rows)
    prefixes: list[str] = []
    previous: str | None = None
    for fingerprint in fingerprints:
        previous = prefix_hash(previous, fingerprint)
        prefixes.append(previous)
    return fingerprints, tuple(prefixes)


def compare_input_histories(previous: Iterable[EmaInputRow], current: Iterable[EmaInputRow]) -> InputHistoryComparison:
    """새 날짜 연장과 과거 revision/deletion을 저장 계층이 구별하도록 돕는다."""
    previous_rows = tuple(previous)
    current_rows = tuple(current)
    previous_fingerprints, _ = build_prefix_hashes(previous_rows)
    current_fingerprints, _ = build_prefix_hashes(current_rows)
    shared = min(len(previous_fingerprints), len(current_fingerprints))
    changed = next(
        (index for index in range(shared) if previous_fingerprints[index] != current_fingerprints[index]),
        None,
    )
    if changed is not None:
        return InputHistoryComparison(InputHistoryKind.REBUILD_REQUIRED, changed, len(previous_rows), len(current_rows))
    if len(current_rows) == len(previous_rows):
        return InputHistoryComparison(InputHistoryKind.UNCHANGED, None, len(previous_rows), len(current_rows))
    if len(current_rows) > len(previous_rows):
        return InputHistoryComparison(InputHistoryKind.PREFIX_EXTENDED, None, len(previous_rows), len(current_rows))
    return InputHistoryComparison(InputHistoryKind.REBUILD_REQUIRED, len(current_rows), len(previous_rows), len(current_rows))


def select_latest_input(rows: Iterable[EmaInputRow], policy: EmaSourcePolicy) -> EmaInputRow | None:
    """정책 후보 중 cutoff 이내의 마지막 ``(observed_at, observation_id)``를 선택한다.

    충돌 판정, validation case·보정 적용은 T3 selector가 입력 status/reason과 snapshot에
    확정해 전달한다. 이 함수는 계약상 정렬 tie-break를 제공할 뿐 DB를 읽지 않는다.
    """
    candidates = [row for row in rows if row.observed_at is not None and policy.accepts(row)]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row.observed_at, -1 if row.observation_id is None else row.observation_id))


def select_last_approved_close_correction(corrections: Iterable[CloseCorrectionEvidence]) -> tuple[Decimal | None, InputReasonCode | None, tuple[int, ...]]:
    """id가 가장 큰 승인 close 보정만 적용하고, 비수치 값은 추측 없이 invalid로 둔다."""
    approved = sorted((item for item in corrections if item.status == "APPROVED"), key=lambda item: item.correction_id)
    if not approved:
        return None, None, ()
    selected = approved[-1]
    if selected.value is None or not selected.value.is_finite():
        return None, InputReasonCode.INVALID_APPROVED_CORRECTION, tuple(item.correction_id for item in approved)
    return selected.value, None, tuple(item.correction_id for item in approved)


def result_hash(values: Iterable[EmaValue]) -> str:
    ordered = sorted(values, key=lambda value: (value.period, value.trade_date))
    return _hash_material([value.result_material() for value in ordered])


def _hash_material(material: Any) -> str:
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be canonicalized")
        # Decimal.normalize() applies the ambient Decimal context and can therefore
        # round a high-precision value. Formatting then trimming zeros preserves
        # the exact coefficient regardless of caller context.
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return "0" if rendered in {"-0", ""} else rendered
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        utc_value = value.astimezone(timezone.utc)
        rendered = utc_value.isoformat(timespec="microseconds")
        return rendered.replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    return value

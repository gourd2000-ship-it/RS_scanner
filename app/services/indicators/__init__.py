"""재현 가능한 EMA 입력 계약과 순수 계산기."""

from app.services.indicators.contracts import (
    EMA_FORMULA_VERSION,
    EMA_PERIODS,
    INPUT_POLICY_VERSION,
    CloseCorrectionEvidence,
    EmaCalculationResult,
    EmaInputRow,
    EmaInputStatus,
    EmaSourcePolicy,
    EmaStatus,
    EmaValue,
    IdentitySnapshot,
    InputHistoryComparison,
    InputHistoryKind,
    InputReasonCode,
    ValidationCaseEvidence,
    build_prefix_hashes,
    canonical_json,
    compare_input_histories,
    input_row_fingerprint,
    prefix_hash,
    result_hash,
    select_last_approved_close_correction,
    select_latest_input,
)
from app.services.indicators.ema import EMA_DECIMAL_PRECISION, compute_ema

__all__ = [
    "EMA_DECIMAL_PRECISION", "EMA_FORMULA_VERSION", "EMA_PERIODS", "INPUT_POLICY_VERSION",
    "CloseCorrectionEvidence", "EmaCalculationResult", "EmaInputRow", "EmaInputStatus",
    "EmaSourcePolicy", "EmaStatus", "EmaValue", "IdentitySnapshot", "InputHistoryComparison",
    "InputHistoryKind", "InputReasonCode", "ValidationCaseEvidence", "build_prefix_hashes",
    "canonical_json", "compare_input_histories", "compute_ema", "input_row_fingerprint", "prefix_hash",
    "result_hash", "select_last_approved_close_correction", "select_latest_input",
]

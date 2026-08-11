"""Small deterministic rules shared by ingestion and batch validation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class RuleFinding:
    rule_id: str
    severity: str
    reason_code: str
    message: str
    evidence: dict[str, Any]
    decision: str | None = None
    case_status: str = "open"


class ValidationRule(Protocol):
    """Extension contract for future deterministic rules."""

    rule_id: str

    def check(self, context: object) -> list[RuleFinding]:
        ...


def inspect_ohlc_row(
    row: object,
    *,
    rule_id: str = "persisted_ohlc",
    allow_null_volume: bool = False,
) -> list[RuleFinding]:
    """Return all deterministic OHLC violations for one ORM/payload row."""

    evidence = {
        field: _json_value(getattr(row, field, None))
        for field in ("open", "high", "low", "close", "volume", "trade_date")
    }
    findings: list[RuleFinding] = []
    values = {
        field: getattr(row, field, None)
        for field in ("open", "high", "low", "close")
    }
    if any(value is None for value in values.values()):
        findings.append(
            _invalid(rule_id, "INVALID_OHLC", "one or more OHLC fields are null", evidence)
        )
        return findings

    if any(not _is_finite(value) for value in values.values()):
        findings.append(
            _invalid(rule_id, "INVALID_PRICE", "OHLC fields must be finite", evidence)
        )
    elif any(value <= 0 for value in values.values()):
        findings.append(
            _invalid(rule_id, "INVALID_PRICE", "OHLC fields must be positive", evidence)
        )
    elif values["low"] > values["high"] or values["low"] > min(
        values["open"], values["close"]
    ) or values["high"] < max(values["open"], values["close"]):
        findings.append(
            _invalid(rule_id, "INVALID_OHLC", "OHLC values are inconsistent", evidence)
        )

    volume = getattr(row, "volume", None)
    if (volume is None and not allow_null_volume) or (volume is not None and volume < 0):
        findings.append(
            _invalid(rule_id, "INVALID_VOLUME", "volume must not be null or negative", evidence)
        )
    return findings


def _invalid(rule_id: str, reason_code: str, message: str, evidence: dict[str, Any]) -> RuleFinding:
    return RuleFinding(
        rule_id=rule_id,
        severity="ERROR",
        reason_code=reason_code,
        message=message,
        evidence={**evidence, "message": message},
        decision="EXCLUDE",
        case_status="auto_resolved",
    )


def _is_finite(value: object) -> bool:
    if isinstance(value, Decimal):
        return value.is_finite()
    try:
        return bool(value == value) and value not in (float("inf"), float("-inf"))
    except (TypeError, ValueError):
        return False


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if hasattr(value, "isoformat") else value

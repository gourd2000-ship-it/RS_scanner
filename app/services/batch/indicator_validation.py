"""Validation gate shared by the optional daily OHLCV indicators."""

def indicator_validation_skip_reason(validation: object | None) -> str | None:
    """Return why an indicator must skip when there is no accepted daily validation."""
    if validation is None:
        return "validation_unavailable"
    run = getattr(validation, "run", None)
    status = getattr(run, "validation_status", None)
    if status not in {"passed", "passed_with_warnings"}:
        return "validation_gate_blocked"
    return None

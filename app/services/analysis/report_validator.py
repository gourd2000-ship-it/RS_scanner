"""Validation for Sam's evidence-based analysis report contract."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re
from typing import Any


MAX_MARKDOWN_BYTES = 512_000
MAX_EVIDENCE_ITEMS = 10
MAX_EVIDENCE_ITEMS_PER_ERROR_TYPE = 3
_SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+\-/=]{12,}|(?:api|app|secret)[_ -]?key\s*[:=]|"
    r"access[_ -]?token\s*[:=]|account(?:[_ -]?number)?\s*[:=])"
)


class AnalysisReportValidationError(ValueError):
    pass


def report_content_hash(markdown_body: str, report_json: dict[str, Any]) -> str:
    """Canonical hash for the two immutable report payloads."""
    canonical_json = json.dumps(
        report_json,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256(f"{markdown_body}\n{canonical_json}".encode("utf-8")).hexdigest()


def validate_analysis_report(
    *,
    request_id: str,
    markdown_body: str,
    report_json: dict[str, Any],
    report_hash: str,
    sample_limit: int,
) -> dict[str, Any]:
    if not markdown_body.strip():
        raise AnalysisReportValidationError("markdown_body is required")
    if len(markdown_body.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise AnalysisReportValidationError("markdown_body exceeds maximum size")
    if report_json.get("schema_version") != 1:
        raise AnalysisReportValidationError("report_json.schema_version must be 1")
    if report_json.get("request_id") != request_id:
        raise AnalysisReportValidationError("report_json.request_id does not match request")
    expected_hash = report_content_hash(markdown_body, report_json)
    if report_hash != expected_hash:
        raise AnalysisReportValidationError("report_hash does not match submitted content")
    _reject_sensitive_content(markdown_body)
    _reject_sensitive_content(report_json)

    findings = _list_field(report_json, "findings")
    recommendations = _list_field(report_json, "recommendations")
    evidence = _list_field(report_json, "kiwoom_evidence")
    limitations = _list_field(report_json, "limitations")
    if not findings and not limitations:
        raise AnalysisReportValidationError("report requires a finding or an explicit limitation")
    if len(evidence) > min(sample_limit, MAX_EVIDENCE_ITEMS):
        raise AnalysisReportValidationError("kiwoom evidence exceeds the request sample limit")

    finding_ids: set[str] = set()
    for finding in findings:
        _require_keys(
            finding,
            {
                "finding_id",
                "error_type",
                "severity",
                "observed_count",
                "sample_refs",
                "evidence_refs",
                "root_cause_hypothesis",
                "confidence",
            },
            "finding",
        )
        finding_id = _required_identifier(finding["finding_id"], "finding_id")
        if finding_id in finding_ids:
            raise AnalysisReportValidationError("finding_id values must be unique")
        finding_ids.add(finding_id)
        if not isinstance(finding["observed_count"], int) or finding["observed_count"] < 0:
            raise AnalysisReportValidationError("finding observed_count must be a non-negative integer")
        _require_reference_list(finding["sample_refs"], "finding sample_refs")
        _require_reference_list(finding["evidence_refs"], "finding evidence_refs")

    evidence_ids: set[str] = set()
    evidence_error_types: Counter[str] = Counter()
    for evidence_item in evidence:
        _require_keys(
            evidence_item,
            {"evidence_id", "symbol", "error_type", "period", "kiwoom", "autobot_db", "comparison", "conclusion"},
            "kiwoom evidence",
        )
        if "rows" in evidence_item or "raw_response" in evidence_item:
            raise AnalysisReportValidationError("kiwoom raw rows and raw responses are not accepted")
        evidence_id = _required_identifier(evidence_item["evidence_id"], "evidence_id")
        if evidence_id in evidence_ids:
            raise AnalysisReportValidationError("evidence_id values must be unique")
        evidence_ids.add(evidence_id)
        error_type = evidence_item["error_type"]
        if not isinstance(error_type, str) or not error_type:
            raise AnalysisReportValidationError("kiwoom evidence error_type must be a non-empty string")
        evidence_error_types[error_type] += 1
        _require_keys(evidence_item["period"], {"from", "to"}, "kiwoom evidence period")
        _require_keys(
            evidence_item["kiwoom"],
            {"status", "row_count", "latest_date", "result_hash"},
            "kiwoom evidence kiwoom",
        )
        _require_keys(
            evidence_item["autobot_db"],
            {"endpoint", "row_count", "latest_date"},
            "kiwoom evidence autobot_db",
        )
        _require_keys(
            evidence_item["comparison"],
            {"matched_dates", "value_differences", "missing_in_db", "missing_in_kiwoom"},
            "kiwoom evidence comparison",
        )
    if any(count > MAX_EVIDENCE_ITEMS_PER_ERROR_TYPE for count in evidence_error_types.values()):
        raise AnalysisReportValidationError(
            "kiwoom evidence exceeds the per-error-type sample limit"
        )
    proposal_ids: set[str] = set()
    for proposal in recommendations:
        _require_keys(
            proposal,
            {
                "proposal_id",
                "finding_ids",
                "priority",
                "risk_level",
                "change_scope",
                "target_files",
                "tests",
                "rollback",
                "evidence_refs",
            },
            "recommendation",
        )
        proposal_id = _required_identifier(proposal["proposal_id"], "proposal_id")
        if proposal_id in proposal_ids:
            raise AnalysisReportValidationError("proposal_id values must be unique")
        proposal_ids.add(proposal_id)
        proposal_finding_ids = _require_reference_list(proposal["finding_ids"], "recommendation finding_ids")
        unknown_finding_ids = set(proposal_finding_ids) - finding_ids
        if unknown_finding_ids:
            raise AnalysisReportValidationError(
                "recommendation references unknown finding_id values: "
                + ", ".join(sorted(unknown_finding_ids))
            )
        proposal_evidence_ids = _require_reference_list(proposal["evidence_refs"], "recommendation evidence_refs")
        unknown_evidence_ids = set(proposal_evidence_ids) - evidence_ids
        if unknown_evidence_ids:
            raise AnalysisReportValidationError(
                "recommendation references unknown evidence_id values: "
                + ", ".join(sorted(unknown_evidence_ids))
            )
        _require_nonempty_string_list(proposal["target_files"], "recommendation target_files")
        _require_nonempty_string_list(proposal["tests"], "recommendation tests")
    return {
        "findings": findings,
        "kiwoom_evidence": evidence,
        "recommendations": recommendations,
        "limitations": limitations,
    }


def _list_field(value: dict[str, Any], field: str) -> list[Any]:
    result = value.get(field, [])
    if not isinstance(result, list):
        raise AnalysisReportValidationError(f"report_json.{field} must be a list")
    return result


def _require_keys(value: Any, required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise AnalysisReportValidationError(f"{label} must be an object")
    missing = sorted(required - set(value))
    if missing:
        raise AnalysisReportValidationError(f"{label} missing required fields: {', '.join(missing)}")


def _required_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisReportValidationError(f"{label} must be a non-empty string")
    return value


def _require_reference_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise AnalysisReportValidationError(f"{label} must be a list of non-empty strings")
    return value


def _require_nonempty_string_list(value: Any, label: str) -> list[str]:
    result = _require_reference_list(value, label)
    if not result:
        raise AnalysisReportValidationError(f"{label} must not be empty")
    return result


def _reject_sensitive_content(value: Any) -> None:
    if isinstance(value, str):
        if _SENSITIVE_VALUE.search(value):
            raise AnalysisReportValidationError("report contains credential-like content")
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in {"token", "secret", "api_key", "app_key", "account", "account_number"}:
                raise AnalysisReportValidationError("report contains a sensitive field")
            _reject_sensitive_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_content(nested)

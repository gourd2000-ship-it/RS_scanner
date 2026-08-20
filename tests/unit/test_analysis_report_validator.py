import pytest

from app.services.analysis.report_validator import (
    AnalysisReportValidationError,
    report_content_hash,
    validate_analysis_report,
)


def _evidence(number: int) -> dict:
    return {
        "evidence_id": f"evidence-{number}",
        "symbol": f"0000{number}",
        "error_type": "invalid_ohlc",
        "period": {"from": "2026-08-01", "to": "2026-08-14"},
        "kiwoom": {
            "status": "succeeded",
            "row_count": 10,
            "latest_date": "2026-08-14",
            "result_hash": "a" * 64,
        },
        "autobot_db": {
            "endpoint": "/internal/v1/crawl-analysis/stock-history/000001",
            "row_count": 10,
            "latest_date": "2026-08-14",
        },
        "comparison": {
            "matched_dates": 10,
            "value_differences": [],
            "missing_in_db": [],
            "missing_in_kiwoom": [],
        },
        "conclusion": "표본 비교 완료",
    }


def test_report_rejects_more_than_three_kiwoom_samples_for_one_error_type():
    report_json = {
        "schema_version": 1,
        "request_id": "analysis-validator-001",
        "findings": [],
        "kiwoom_evidence": [_evidence(index) for index in range(4)],
        "recommendations": [],
        "limitations": ["표본은 오류 유형별 상한을 넘으면 안 됨"],
    }
    markdown = "# 분석 보고서\n증거 제한 검증"

    with pytest.raises(AnalysisReportValidationError, match="per-error-type"):
        validate_analysis_report(
            request_id="analysis-validator-001",
            markdown_body=markdown,
            report_json=report_json,
            report_hash=report_content_hash(markdown, report_json),
            sample_limit=10,
        )


def test_report_identifies_unknown_recommendation_evidence_id():
    report_json = {
        "schema_version": 1,
        "request_id": "analysis-validator-002",
        "findings": [
            {
                "finding_id": "finding-001",
                "error_type": "invalid_ohlc",
                "severity": "high",
                "observed_count": 1,
                "sample_refs": ["failure-1"],
                "evidence_refs": ["evidence-1"],
                "root_cause_hypothesis": "validation classification is too coarse",
                "confidence": "medium",
            }
        ],
        "kiwoom_evidence": [_evidence(1)],
        "recommendations": [
            {
                "proposal_id": "proposal-001",
                "finding_ids": ["finding-001"],
                "priority": "P0",
                "risk_level": "medium",
                "change_scope": "classify empty rows",
                "target_files": ["app/services/batch/sync_prices.py"],
                "tests": ["classification test"],
                "rollback": "feature flag off",
                "evidence_refs": ["evidence-missing"],
            }
        ],
        "limitations": [],
    }
    markdown = "# 분석 보고서\n증거 참조 검증"

    with pytest.raises(
        AnalysisReportValidationError,
        match="unknown evidence_id values: evidence-missing",
    ):
        validate_analysis_report(
            request_id="analysis-validator-002",
            markdown_body=markdown,
            report_json=report_json,
            report_hash=report_content_hash(markdown, report_json),
            sample_limit=10,
        )

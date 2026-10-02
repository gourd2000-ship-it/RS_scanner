"""감사 결과의 종목·연도별 사용 가능 구간 판정."""

import csv

from app.services.validation.cleansing_assessment import assess_coverage


def test_assessment_preserves_complete_partial_and_unavailable(tmp_path):
    with (tmp_path / "symbol_year_coverage.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("instrument_id", "code", "year", "market", "expected", "observed",
                         "valid", "missing", "invalid", "review_required", "non_tradable"))
        writer.writerow((1, "000001", 2020, "KOSPI", 2, 2, 2, 0, 0, 0, 0))
        writer.writerow((2, "000002", 2020, "KOSPI", 2, 1, 1, 1, 0, 0, 0))
        writer.writerow((3, "000003", 2020, "KOSPI", 2, 0, 0, 2, 0, 0, 0))
    result = assess_coverage(tmp_path)
    assert result == {"complete": 1, "partial": 1, "unavailable": 1}
    with (tmp_path / "segment_assessment.csv").open() as stream:
        assert [row["status"] for row in csv.DictReader(stream)] == [
            "complete", "partial", "unavailable"
        ]

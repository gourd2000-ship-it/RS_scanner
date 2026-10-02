"""OHLCV 감사의 종목·연도별 사용 가능성을 결측까지 포함해 요약한다."""

from collections import Counter
import csv
import json
from pathlib import Path


def assess_coverage(audit_dir: Path) -> dict[str, int]:
    """모든 기대 행이 valid인 구간만 complete로 판정한다."""
    output = audit_dir / "segment_assessment.csv"
    counts: Counter[str] = Counter()
    with (audit_dir / "symbol_year_coverage.csv").open(newline="", encoding="utf-8") as source, \
            output.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=[*reader.fieldnames, "status"])
        writer.writeheader()
        for row in reader:
            expected = int(row["expected"])
            if expected == 0:
                continue
            valid = int(row["valid"])
            classified = sum(int(row[name]) for name in
                             ("valid", "missing", "invalid", "review_required"))
            if classified != expected:
                raise ValueError(f"coverage count mismatch: {row['instrument_id']} {row['year']}")
            status = "complete" if valid == expected else "unavailable" if valid == 0 else "partial"
            counts[status] += 1
            writer.writerow({**row, "status": status})
    result = {key: counts[key] for key in ("complete", "partial", "unavailable")}
    (audit_dir / "assessment.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

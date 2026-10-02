"""상폐를 제외하고 결측 재조회 후보와 요청 상한을 계산한다."""

import csv
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import ceil
from pathlib import Path


@dataclass(frozen=True)
class RepairTarget:
    instrument_id: int
    code: str
    dates: tuple[str, ...]
    estimated_requests: int


@dataclass(frozen=True)
class RepairPlan:
    targets: tuple[RepairTarget, ...]
    pending_instrument_count: int
    excluded_delisted_count: int
    request_budget: int
    estimated_requests: int
    manifest_hash: str


def build_repair_plan(audit_dir: Path, *, request_budget: int = 0) -> RepairPlan:
    """기존 공급자 재조회 후보만 계획한다. 이 함수는 네트워크·DB를 쓰지 않는다."""
    if request_budget < 0:
        raise ValueError("request_budget must be non-negative")
    manifest = json.loads((audit_dir / "manifest.json").read_text(encoding="utf-8"))
    end_date = date.fromisoformat(manifest["end"])
    with (audit_dir / "excluded_universe.csv").open(newline="", encoding="utf-8") as stream:
        excluded = {int(row["instrument_id"]) for row in csv.DictReader(stream)}
    gaps: dict[int, tuple[str, list[str]]] = {}
    with (audit_dir / "gaps.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            instrument_id = int(row["instrument_id"])
            if instrument_id in excluded:
                continue
            code, dates = gaps.setdefault(instrument_id, (row["code"], []))
            dates.append(row["trade_date"])
    candidates = tuple(
        RepairTarget(instrument_id=instrument_id, code=code, dates=tuple(sorted(set(dates))),
                     estimated_requests=max(1, ceil(((end_date - date.fromisoformat(min(dates))).days + 1) / 600)))
        for instrument_id, (code, dates) in sorted(gaps.items())
    )
    selected = []
    used = 0
    for target in candidates:
        if used + target.estimated_requests > request_budget:
            continue
        selected.append(target)
        used += target.estimated_requests
    material = {
        "version": "ohlcv-repair-plan-v1", "request_budget": request_budget,
        "excluded_delisted": sorted(excluded),
        "candidates": [target.__dict__ for target in candidates],
    }
    manifest_hash = sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return RepairPlan(tuple(selected), len(candidates) - len(selected), len(excluded),
                      request_budget, used, manifest_hash)

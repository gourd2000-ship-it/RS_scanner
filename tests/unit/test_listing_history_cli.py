"""Contract tests for the approved-file BT03 importer input format."""

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[2] / "scripts/import_listing_history.py"
    spec = importlib.util.spec_from_file_location("import_listing_history", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_file_importer_preserves_codes_and_builds_source_backed_event_input():
    module = _module()

    event = module.parse_event(
        {
            "instrument_id": 7,
            "source_record_key": "230980:2026-06-05",
            "event_type": "delisted",
            "effective_from": "2026-06-05",
            "last_trading_date": "2026-06-04",
            "market": "KOSDAQ",
            "provider_code": "0230980A",
            "evidence_state": "observed",
            "payload": {"code": "0230980A", "delisting_date": "2026-06-05"},
        },
        source="kind_export",
        source_contract_version="kind-delisting-export-v1",
        source_url="https://kind.krx.co.kr/investwarn/delcompany.do",
        parser_version="listing-history-json-v1",
    )

    assert event.instrument_id == 7
    assert event.provider_code == "0230980A"
    assert event.payload["code"] == "0230980A"
    assert event.published_at is None

import json
from datetime import date

import pytest

from app.core.config import Settings
from app.core.exceptions import PriceFetchError, ValidationError
from app.crawler.kiwoom_file_bridge import KiwoomFileBridgeClient
from app.crawler.sources.kiwoom import create_kiwoom_fallback_source
from app.crawler.sources.kiwoom_file import KiwoomFileBridgePriceSource


def _row(day: str, close: int = 100) -> dict[str, object]:
    return {
        "date": day,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
        "change_rate": 0,
    }


def _settings(root, **overrides):
    values = {
        "KIWOOM_BRIDGE_DIR": str(root),
        "KIWOOM_BRIDGE_TIMEOUT": 1.0,
        "KIWOOM_BRIDGE_POLL_INTERVAL": 0.01,
    }
    values.update(overrides)
    return Settings(**values)


def _make_layout(root):
    for name in ("requests", "processing", "results", "payload"):
        (root / name).mkdir(parents=True)


def test_file_bridge_writes_request_and_reads_sam_result(tmp_path):
    _make_layout(tmp_path)
    settings = _settings(tmp_path)

    def sam_sleep(_delay):
        request_path = next((tmp_path / "requests").glob("*.request.json"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "status": "succeeded",
            "items": [
                {
                    "symbol": "005930",
                    "status": "succeeded",
                    "adjusted_price": True,
                    "retry_count": 1,
                    "rows": [_row("20260812", 100), _row("20260813", 101)],
                }
            ],
        }
        (tmp_path / "results" / f"{request['request_id']}.result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )

    parsed = KiwoomFileBridgeClient(settings=settings, sleep=sam_sleep).fetch_daily_chart(
        "005930"
    )

    request = json.loads(
        next((tmp_path / "requests").glob("*.request.json")).read_text(encoding="utf-8")
    )
    assert request["operation"] == "daily_chart"
    assert request["symbols"] == ["005930"]
    assert request["adjusted_price"] is True
    assert [row.trade_date for row in parsed] == [date(2026, 8, 12), date(2026, 8, 13)]
    assert parsed.retry_count == 1


def test_file_bridge_rejects_adjusted_price_mismatch(tmp_path):
    _make_layout(tmp_path)
    settings = _settings(tmp_path)

    def sam_sleep(_delay):
        request_path = next((tmp_path / "requests").glob("*.request.json"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result = {
            "request_id": request["request_id"],
            "status": "succeeded",
            "items": [
                {
                    "symbol": "005930",
                    "status": "succeeded",
                    "adjusted_price": False,
                    "rows": [_row("20260813")],
                }
            ],
        }
        (tmp_path / "results" / f"{request['request_id']}.result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )

    with pytest.raises(ValidationError, match="adjusted-price"):
        KiwoomFileBridgeClient(settings=settings, sleep=sam_sleep).fetch_daily_chart(
            "005930"
        )


def test_file_bridge_timeout_preserves_provider_failure(tmp_path):
    _make_layout(tmp_path)
    clock = [0.0]

    def monotonic():
        return clock[0]

    def advance(delay):
        clock[0] += delay

    settings = _settings(tmp_path, KIWOOM_BRIDGE_TIMEOUT=0.5)
    with pytest.raises(PriceFetchError, match="timed out"):
        KiwoomFileBridgeClient(
            settings=settings,
            sleep=advance,
            monotonic=monotonic,
        ).fetch_daily_chart("005930")


def test_file_bridge_source_filters_since_date_and_factory_uses_settings(tmp_path):
    _make_layout(tmp_path)
    settings = _settings(
        tmp_path,
        KIWOOM_FALLBACK_TRANSPORT="sam_file",
    )
    source = create_kiwoom_fallback_source(settings)

    assert isinstance(source, KiwoomFileBridgePriceSource)
    assert source.client.settings.kiwoom_bridge_dir == str(tmp_path)

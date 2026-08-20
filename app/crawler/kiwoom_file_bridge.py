"""File-based Kiwoom bridge executed by Hermes Agent Sam."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.core.exceptions import KiwoomApiError, PriceFetchError, PriceParseError, ValidationError
from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices


_CODE_RE = re.compile(r"^\d{6}$")
_FINAL_STATUSES = {"succeeded", "partial", "failed", "rejected", "expired"}


class KiwoomFileBridgeClient:
    """Submit one read-only daily-chart request and wait for Sam's result."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        root_dir: str | Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        self.root = Path(root_dir or self.settings.kiwoom_bridge_dir)
        self.requests_dir = self.root / "requests"
        self.processing_dir = self.root / "processing"
        self.results_dir = self.root / "results"
        self.payload_dir = self.root / "payload"
        self.sleep = sleep
        self.monotonic = monotonic

    def _request_url(self, request_id: str) -> str:
        return f"kiwoom-file://daily_chart/{request_id}"

    def _validate_layout(self) -> None:
        required = (
            self.requests_dir,
            self.processing_dir,
            self.results_dir,
            self.payload_dir,
        )
        missing = [str(path) for path in required if not path.is_dir()]
        if missing:
            raise PriceFetchError(
                "kiwoom file bridge directories are missing",
                url=f"kiwoom-file://{self.root}",
            )
        if not os.access(self.requests_dir, os.W_OK):
            raise PriceFetchError(
                "kiwoom file bridge requests directory is not writable",
                url=f"kiwoom-file://{self.requests_dir}",
            )

    def _target_date(self) -> date:
        try:
            zone = ZoneInfo(self.settings.batch_timezone)
        except Exception:  # noqa: BLE001
            zone = timezone.utc
        return datetime.now(zone).date()

    def _write_request(self, request: dict[str, Any]) -> Path:
        request_id = str(request["request_id"])
        final_path = self.requests_dir / f"{request_id}.request.json"
        temporary_path: Path | None = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{request_id}.",
                suffix=".tmp",
                dir=self.requests_dir,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(request, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o660)
            os.replace(temporary_path, final_path)
            return final_path
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PriceFetchError(
                "failed to write kiwoom bridge request",
                url=f"kiwoom-file://{self.requests_dir}",
            ) from exc

    def _build_request(self, code: str, since_date: date | None) -> dict[str, Any]:
        request_id = f"rs-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:12]}"
        request: dict[str, Any] = {
            "schema_version": 1,
            "request_id": request_id,
            "idempotency_key": request_id,
            "operation": "daily_chart",
            "provider": "kiwoom",
            "symbols": [code],
            "target_date": self._target_date().isoformat(),
            "history_from": since_date.isoformat() if since_date else None,
            "adjusted_price": str(
                getattr(self.settings, "kiwoom_adjusted_price_type", "1")
            ).lower()
            in {"1", "true", "yes", "y"},
            "max_rows_per_symbol": self.settings.kiwoom_bridge_max_rows_per_symbol,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(
                time.time() + self.settings.kiwoom_bridge_timeout,
                tz=timezone.utc,
            ).isoformat(),
            "requested_by": "rs_scanner",
        }
        profile = (self.settings.kiwoom_cli_profile or "").strip()
        if profile:
            request["profile"] = profile
        return request

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    def _load_data_file(self, value: Any, expected_sha256: str | None) -> Any:
        if not isinstance(value, str) or not value:
            raise ValidationError("kiwoom bridge result data_file is invalid")
        candidate = (self.root / value).resolve()
        payload_root = self.payload_dir.resolve()
        if not candidate.is_relative_to(payload_root) or not candidate.is_file():
            raise ValidationError("kiwoom bridge data_file is outside payload directory")

        raw = candidate.read_bytes()
        if expected_sha256:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected_sha256:
                raise ValidationError("kiwoom bridge payload checksum mismatch")
        if candidate.name.endswith(".gz"):
            raw = gzip.decompress(raw)

        text = raw.decode("utf-8")
        if candidate.name.endswith(".jsonl") or candidate.name.endswith(".jsonl.gz"):
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.loads(text)

    def _find_item(self, payload: dict[str, Any], code: str) -> dict[str, Any]:
        for key in ("items", "results"):
            values = payload.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and str(item.get("symbol")) == code:
                        return item
        if str(payload.get("symbol")) == code:
            return payload
        raise PriceFetchError(
            "kiwoom bridge result has no item for requested symbol",
            url=self._request_url(str(payload.get("request_id") or "unknown")),
        )

    def _parse_result(
        self,
        result_path: Path,
        *,
        request: dict[str, Any],
        code: str,
    ):
        response_bytes = result_path.stat().st_size
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PriceParseError(
                "kiwoom bridge result is not valid JSON",
                response_bytes=response_bytes,
            ) from exc
        if not isinstance(payload, dict):
            raise PriceParseError(
                "kiwoom bridge result must be a JSON object",
                response_bytes=response_bytes,
            )
        if payload.get("request_id") != request["request_id"]:
            raise ValidationError("kiwoom bridge result request_id mismatch")

        item = self._find_item(payload, code)
        item_status = str(item.get("status") or payload.get("status") or "failed")
        if item_status in {"failed", "rejected", "expired", "skipped"}:
            retry_count = int(item.get("retry_count") or payload.get("retry_count") or 0)
            raise KiwoomApiError(
                str(item.get("error_message") or payload.get("error_message") or "kiwoom bridge request failed"),
                url=self._request_url(str(request["request_id"])),
                api_code=item.get("error_code") or payload.get("error_code"),
                retry_count=retry_count,
                response_bytes=response_bytes,
            )

        expected_adjusted = self._as_bool(request.get("adjusted_price"))
        if "adjusted_price" in item and self._as_bool(item["adjusted_price"]) != expected_adjusted:
            raise ValidationError("kiwoom bridge adjusted-price policy mismatch")

        rows_payload = item.get("rows")
        if rows_payload is None and isinstance(item.get("data"), (list, dict)):
            rows_payload = item["data"]
        if rows_payload is None and item.get("data_file"):
            rows_payload = self._load_data_file(item["data_file"], item.get("sha256"))
        parsed = parse_kiwoom_daily_prices(
            rows_payload,
            response_bytes=response_bytes,
        )
        return type(parsed)(
            list(parsed),
            invalid_rows=parsed.invalid_rows,
            response_bytes=response_bytes,
            retry_count=int(item.get("retry_count") or payload.get("retry_count") or 0),
        )

    def fetch_daily_chart(self, code: str, since_date: date | None = None):
        if not _CODE_RE.fullmatch(code):
            raise ValidationError("kiwoom bridge symbol must be a six-digit code")
        self._validate_layout()
        request = self._build_request(code, since_date)
        self._write_request(request)
        result_path = self.results_dir / f"{request['request_id']}.result.json"
        deadline = self.monotonic() + self.settings.kiwoom_bridge_timeout

        while True:
            if result_path.is_file():
                return self._parse_result(result_path, request=request, code=code)
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise PriceFetchError(
                    "kiwoom bridge result polling timed out",
                    url=self._request_url(str(request["request_id"])),
                )
            self.sleep(min(self.settings.kiwoom_bridge_poll_interval, remaining))

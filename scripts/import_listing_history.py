#!/usr/bin/env python3
"""Import an approved historical listing-event export without inferring price dates.

The input must be a JSON array, or an object with an ``events`` array.  Each
event explicitly names a canonical ``instrument_id`` so a reused short code is
never resolved by display name or silently attached to a legacy price symbol.
"""

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.database import session_scope
from app.repositories.listing_history_repository import ListingEventInput, ListingHistoryRepository


def parse_event(
    row: dict[str, Any],
    *,
    source: str,
    source_contract_version: str,
    source_url: str | None,
    parser_version: str,
) -> ListingEventInput:
    """Convert a checked export row while retaining its original payload evidence."""
    try:
        instrument_id = row["instrument_id"]
        if not isinstance(instrument_id, int) or isinstance(instrument_id, bool) or instrument_id <= 0:
            raise ValueError("instrument_id must be a positive integer")
        source_record_key = _required_text(row, "source_record_key")
        event_type = _required_text(row, "event_type")
        effective_from = _parse_date(row, "effective_from", required=True)
        evidence_state = _required_text(row, "evidence_state")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid listing event: {exc}") from exc

    payload = row.get("payload", row)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return ListingEventInput(
        instrument_id=instrument_id,
        source=source,
        source_contract_version=source_contract_version,
        source_record_key=source_record_key,
        source_url=source_url,
        event_type=event_type,
        effective_from=effective_from,
        effective_to=_parse_date(row, "effective_to"),
        published_at=_parse_datetime(row, "published_at"),
        last_trading_date=_parse_date(row, "last_trading_date"),
        market=_optional_text(row, "market"),
        market_to=_optional_text(row, "market_to"),
        provider_code=_optional_text(row, "provider_code"),
        provider_code_to=_optional_text(row, "provider_code_to"),
        trading_status=_optional_text(row, "trading_status"),
        reason=_optional_text(row, "reason"),
        evidence_state=evidence_state,
        payload=payload,
        parser_version=parser_version,
    )


def _required_text(row: dict[str, Any], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _optional_text(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text when supplied")
    return value


def _parse_date(row: dict[str, Any], field: str, *, required: bool = False) -> date | None:
    value = row.get(field)
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD text")
    return date.fromisoformat(value)


def _parse_datetime(row: dict[str, Any], field: str) -> datetime | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be ISO-8601 text")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_rows(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    document = json.loads(raw)
    rows = document["events"] if isinstance(document, dict) else document
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("input must be a JSON event array or an object with an events array")
    return raw, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="approved JSON export")
    parser.add_argument("--source", required=True, help="contracted source identifier, e.g. kind_export")
    parser.add_argument("--source-contract-version", required=True)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--parser-version", default="listing-history-json-v1")
    parser.add_argument("--dry-run", action="store_true", help="parse and validate without committing")
    args = parser.parse_args()

    raw, rows = _load_rows(args.input)
    source_file_hash = hashlib.sha256(raw).hexdigest()
    events = [
        parse_event(
            row,
            source=args.source,
            source_contract_version=args.source_contract_version,
            source_url=args.source_url,
            parser_version=args.parser_version,
        )
        for row in rows
    ]
    created = 0
    duplicates = 0
    with session_scope() as session:
        repository = ListingHistoryRepository(session)
        for event in events:
            result = repository.ingest(event, source_file_hash=source_file_hash)
            created += int(result.created)
            duplicates += int(not result.created)
        if args.dry_run:
            session.rollback()
    print(
        json.dumps(
            {
                "source": args.source,
                "source_contract_version": args.source_contract_version,
                "source_file_hash": source_file_hash,
                "events_read": len(events),
                "created": created,
                "duplicates": duplicates,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

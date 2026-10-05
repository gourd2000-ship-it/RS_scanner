"""Read-only, canonical approval manifest for persisted Volume MA50 history."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.indicators.contracts import EmaSourcePolicy
from scripts.volume_sma50_operations import VolumeStorageRequest, begin_snapshot, build_manifest, canonical_document, write_document


def _date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('date must be YYYY-MM-DD') from exc


def _utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('cutoff must be a UTC RFC 3339 timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError('cutoff requires a UTC offset or Z')
    return parsed.astimezone(UTC)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=_date, required=True)
    parser.add_argument('--end', type=_date, required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--adjustment-type', required=True)
    parser.add_argument('--parser-version', action='append', required=True)
    parser.add_argument('--observation-cutoff', type=_utc, required=True)
    parser.add_argument('--instrument-id', type=int, action='append', default=[])
    parser.add_argument('--output', type=Path, help='canonical JSON approval manifest (default stdout)')
    return parser


def execute(args):
    policy = EmaSourcePolicy(args.provider, args.adjustment_type, tuple(sorted(set(args.parser_version))),
                            args.observation_cutoff)
    request = VolumeStorageRequest(args.start, args.end, policy, tuple(args.instrument_id))
    with SessionLocal() as session:
        begin_snapshot(session, readonly=True)
        return build_manifest(session, request)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = execute(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output:
        write_document(args.output, manifest)
        print(f"Volume MA50 read-only manifest: {args.output} hash={manifest['manifest_hash']}")
    else:
        print(canonical_document(manifest), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

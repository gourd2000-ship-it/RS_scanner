"""Apply a reviewed ATR14 manifest with instrument commits and resume.

Example (only after the operator reviews the plan and migration/backup state)::

    python scripts/backfill_atr14.py --apply --manifest plan.json \
        --manifest-hash REVIEWED_SHA256 --checkpoint checkpoint.json --output apply.json

Repeat with --resume after interruption. No provider requests or price writes occur.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from scripts.atr14_operations import apply_manifest, canonical_document, load_manifest, write_document


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-hash', required=True, help='SHA-256 independently recorded during plan review')
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='explicitly authorize reviewed indicator writes')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--output', type=Path)
    return parser


def execute(args):
    if not args.apply:
        raise ValueError('--apply is required; first run plan_atr14_storage.py and review its manifest')
    paths = [args.manifest.resolve(), args.checkpoint.resolve()]
    if args.output:
        paths.append(args.output.resolve())
    if len(set(paths)) != len(paths):
        raise ValueError('manifest, checkpoint and output paths must be different')
    manifest = load_manifest(args.manifest, args.manifest_hash)
    with SessionLocal() as session:
        return apply_manifest(session, manifest, checkpoint_path=args.checkpoint, resume=args.resume)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = execute(args)
    except (ValueError, OSError) as exc:
        # OSError text may contain private file paths; report its class only.
        parser.error(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    if args.output:
        write_document(args.output, report)
        print(f"ATR14 apply report: {args.output} run_id={report['run_id']} "
              f"created={report['created']} reused={report['reused']} failed={report['failed']}")
    else:
        print(canonical_document(report), end='')
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

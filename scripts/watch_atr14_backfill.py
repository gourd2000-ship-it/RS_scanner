"""Wait for the existing ATR14 writer, then resume if needed and audit its DB result.

Run in an independent container with the host PID namespace. Only one ATR14
writer is allowed; this watcher does no database writes until every writer exits.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from time import sleep

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def active_writer_pids(proc_root: Path = Path('/proc')) -> list[int]:
    found = []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            executable = (process / 'comm').read_text(encoding='utf-8').strip()
            arguments = (process / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if 'python' not in executable:
            continue
        if any(argument == b'scripts/backfill_atr14.py'
               or argument.endswith(b'/scripts/backfill_atr14.py') for argument in arguments):
            found.append(int(process.name))
    return sorted(found)


def wait_for_writers(poll_seconds: int) -> None:
    while True:
        writers = active_writer_pids()
        if not writers:
            return
        print(f'ATR14 writer active: {writers}', flush=True)
        sleep(poll_seconds)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-hash', required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--completed-apply-report', type=Path, required=True)
    parser.add_argument('--reconciliation-report', type=Path, required=True)
    parser.add_argument('--poll-seconds', type=int, default=60)
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        parser.error('--poll-seconds must be positive')
    wait_for_writers(args.poll_seconds)

    if not args.completed_apply_report.is_file():
        if active_writer_pids():
            raise RuntimeError('ATR14 writer appeared before resume')
        print('ATR14 original writer exited without a report; resuming checkpoint', flush=True)
        completed = subprocess.run([
            sys.executable, str(Path(__file__).with_name('backfill_atr14.py')),
            '--manifest', str(args.manifest), '--manifest-hash', args.manifest_hash,
            '--checkpoint', str(args.checkpoint), '--apply', '--resume',
            '--output', str(args.completed_apply_report),
        ], check=False)
        if completed.returncode not in (0, 1) or not args.completed_apply_report.is_file():
            raise RuntimeError(f'ATR14 resume did not produce an apply report (exit={completed.returncode})')

    wait_for_writers(args.poll_seconds)
    completed = subprocess.run([
        sys.executable, str(Path(__file__).with_name('reconcile_atr14_checkpoint.py')),
        '--manifest', str(args.manifest), '--manifest-hash', args.manifest_hash,
        '--checkpoint', str(args.checkpoint),
        '--completed-apply-report', str(args.completed_apply_report),
        '--output', str(args.reconciliation_report), '--apply',
    ], check=False)
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())

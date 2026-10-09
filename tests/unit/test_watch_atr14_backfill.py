"""The ATR14 completion watcher must notice an existing host writer."""
from types import SimpleNamespace

from scripts import watch_atr14_backfill as watcher
from scripts.watch_atr14_backfill import active_writer_pids


def test_active_writer_detection_only_matches_python_backfill(tmp_path):
    writer = tmp_path / '100'
    writer.mkdir()
    (writer / 'comm').write_text('python\n')
    (writer / 'cmdline').write_bytes(b'python\0scripts/backfill_atr14.py\0--apply\0')
    other = tmp_path / '200'
    other.mkdir()
    (other / 'comm').write_text('python\n')
    (other / 'cmdline').write_bytes(b'python\0scripts/watch_atr14_backfill.py\0')
    assert active_writer_pids(tmp_path) == [100]


def test_watcher_waits_for_writer_then_resumes_and_reconciles(tmp_path, monkeypatch):
    manifest = tmp_path / 'manifest.json'
    checkpoint = tmp_path / 'checkpoint.json'
    apply_report = tmp_path / 'apply.json'
    final_report = tmp_path / 'final.json'
    calls = []
    writer_states = iter([[100], [], [], []])
    monkeypatch.setattr(watcher, 'active_writer_pids', lambda: next(writer_states))
    monkeypatch.setattr(watcher, 'sleep', lambda seconds: calls.append(('wait', seconds)))

    def run(command, *, check):
        calls.append(('run', command))
        if 'backfill_atr14.py' in command[1]:
            apply_report.touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(watcher.subprocess, 'run', run)
    result = watcher.main([
        '--manifest', str(manifest), '--manifest-hash', 'a' * 64,
        '--checkpoint', str(checkpoint), '--completed-apply-report', str(apply_report),
        '--reconciliation-report', str(final_report), '--poll-seconds', '1',
    ])
    assert result == 0
    assert calls[0] == ('wait', 1)
    assert 'backfill_atr14.py' in calls[1][1][1]
    assert 'reconcile_atr14_checkpoint.py' in calls[2][1][1]


def test_watcher_waits_for_late_writer_before_reconciliation(tmp_path, monkeypatch):
    apply_report = tmp_path / 'apply.json'
    apply_report.touch()
    states = iter([[], [200], []])
    calls = []
    monkeypatch.setattr(watcher, 'active_writer_pids', lambda: next(states))
    monkeypatch.setattr(watcher, 'sleep', lambda seconds: calls.append('wait'))
    monkeypatch.setattr(watcher.subprocess, 'run', lambda command, *, check:
        calls.append('reconcile') or SimpleNamespace(returncode=0))
    result = watcher.main([
        '--manifest', str(tmp_path / 'manifest.json'), '--manifest-hash', 'a' * 64,
        '--checkpoint', str(tmp_path / 'checkpoint.json'),
        '--completed-apply-report', str(apply_report),
        '--reconciliation-report', str(tmp_path / 'final.json'), '--poll-seconds', '1',
    ])
    assert result == 0
    assert calls == ['wait', 'reconcile']

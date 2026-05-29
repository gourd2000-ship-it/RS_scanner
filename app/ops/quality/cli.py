import argparse
from pathlib import Path

from app.ops.quality.auto_fix_loop import AutoCorrectionLoop
from app.ops.quality.garbage_collector import GarbageCollectorAgent
from app.ops.quality.hook_runner import HookRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Quality harness CLI")
    parser.add_argument("command", choices=["hook", "auto-fix", "gc"])
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.command == "hook":
        return HookRunner(project_root).exit_code()

    if args.command == "auto-fix":
        report = AutoCorrectionLoop(project_root, max_attempts=args.max_attempts).run()
        return 0 if report.success else 1

    result = GarbageCollectorAgent(project_root).scan()
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

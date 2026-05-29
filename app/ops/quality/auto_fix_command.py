import json
import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    report_path = os.getenv("CODEX_QUALITY_REPORT")
    prompt_path = os.getenv("CODEX_AUTO_FIX_PROMPT")

    if not report_path:
        logger.error("CODEX_QUALITY_REPORT is not set")
        return 1

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    failing = [item for item in report if not item.get("passed", False)]

    output_dir = Path(report_path).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "failing_checks": [item["name"] for item in failing],
        "next_action": "connect this command to your Codex/OpenAI execution flow",
        "prompt_path": prompt_path,
    }
    (output_dir / "auto-fix-command-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("auto-fix command template executed")
    logger.info("prompt template: %s", prompt_path)
    logger.info("failing checks: %s", ", ".join(summary["failing_checks"]) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

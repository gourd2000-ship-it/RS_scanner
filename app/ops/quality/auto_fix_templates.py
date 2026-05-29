from pathlib import Path


AUTO_FIX_PROMPT_TEMPLATE = """You are an automated code correction worker for the rs_scanner project.

Input:
- Quality report JSON path: {report_path}
- Project root: {project_root}

Task:
1. Read the quality report JSON.
2. Identify the failing checks and associated findings.
3. Make the smallest safe code changes needed to fix the failures.
4. Avoid broad refactors.
5. Do not change behavior unless the failing check requires it.
6. Re-run the relevant checks after edits if your environment supports it.

Output:
- Short summary of changes
- Files changed
- Remaining risks if any
"""


def write_prompt_template(project_root: str | Path, report_path: str | Path, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        AUTO_FIX_PROMPT_TEMPLATE.format(
            project_root=Path(project_root).resolve(),
            report_path=Path(report_path).resolve(),
        ),
        encoding="utf-8",
    )
    return output

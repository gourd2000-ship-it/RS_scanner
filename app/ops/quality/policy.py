from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GarbageRule:
    rule_id: str
    pattern: str
    severity: str
    message: str
    suggestion: str
    include_globs: tuple[str, ...] = ("app/**/*.py", "tests/**/*.py")


DEFAULT_GARBAGE_RULES: tuple[GarbageRule, ...] = (
    GarbageRule(
        rule_id="debug-print",
        pattern="print(",
        severity="warning",
        message="debug print statement detected",
        suggestion="replace with structured logging or remove the temporary print",
    ),
    GarbageRule(
        rule_id="todo-leftover",
        pattern="TODO",
        severity="info",
        message="leftover TODO marker detected",
        suggestion="convert TODO into a tracked issue or complete the work",
    ),
    GarbageRule(
        rule_id="fixme-leftover",
        pattern="FIXME",
        severity="warning",
        message="leftover FIXME marker detected",
        suggestion="either fix the issue now or track it outside the codebase",
    ),
    GarbageRule(
        rule_id="commented-code",
        pattern="# ",
        severity="info",
        message="review whether this comment hides dead code or stale explanation",
        suggestion="delete dead code comments and keep only durable design comments",
    ),
    GarbageRule(
        rule_id="wildcard-import",
        pattern="import *",
        severity="warning",
        message="wildcard import detected",
        suggestion="replace wildcard imports with explicit symbols for readability and safety",
    ),
    GarbageRule(
        rule_id="bare-except",
        pattern="except:",
        severity="error",
        message="bare except detected",
        suggestion="catch specific exceptions and log the failure context",
    ),
    GarbageRule(
        rule_id="breakpoint-leftover",
        pattern="breakpoint(",
        severity="error",
        message="debugger breakpoint detected",
        suggestion="remove leftover debugger statements before merging",
    ),
    GarbageRule(
        rule_id="noqa-blanket",
        pattern="# noqa ",
        severity="info",
        message="broad noqa suppression detected",
        suggestion="scope the suppression to a concrete rule or remove it if no longer needed",
    ),
)


def iter_candidate_files(root: Path, include_globs: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pattern in include_globs:
        files.extend(root.glob(pattern))
    return sorted({path for path in files if path.is_file() and "__pycache__" not in path.parts})

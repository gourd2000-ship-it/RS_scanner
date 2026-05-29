from pathlib import Path


def load_html_fixture(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")

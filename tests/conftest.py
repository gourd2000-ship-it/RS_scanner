"""Apply stable markers from the repository's test layout."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep the default unit-test selector from collecting database/API suites."""
    for item in items:
        path_parts = set(item.path.parts)
        stem_parts = set(item.path.stem.split("_"))

        if "integration" in path_parts or "e2e" in path_parts:
            item.add_marker(pytest.mark.integration)
        if "e2e" in path_parts:
            item.add_marker(pytest.mark.e2e)
        if "api" in path_parts or "api" in stem_parts:
            item.add_marker(pytest.mark.api)

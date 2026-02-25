"""Scenario registry — loads YAML scenario files from the fixtures/scenarios/ directory.

Each scenario YAML has:
  - name: unique identifier matching the eval case name
  - description: human-readable explanation of what the scenario tests
  - tools: dict keyed by tool name, each containing either:
      - _default: the canned output the mock tool should return
      - _error: an error message string (tool raises ToolException)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_SCENARIOS_DIR = Path(__file__).parent / "scenarios"


@lru_cache(maxsize=32)
def load_scenario(name: str) -> dict[str, Any]:
    """Load a single scenario by name.

    Args:
        name: The scenario filename (without .yaml extension).

    Returns:
        Parsed scenario dict.

    Raises:
        FileNotFoundError: If no scenario file exists for the given name.
    """
    path = _SCENARIOS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No scenario file found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_all_scenarios() -> list[dict[str, Any]]:
    """Load all scenario YAML files from the scenarios directory.

    Returns:
        List of parsed scenario dicts, sorted by filename.
    """
    scenarios = []
    for path in sorted(_SCENARIOS_DIR.glob("*.yaml")):
        with open(path) as f:
            scenarios.append(yaml.safe_load(f))
    return scenarios


def get_fixture(scenario_name: str, tool_name: str) -> dict[str, Any] | None:
    """Get the fixture data for a specific tool in a scenario.

    Returns the canned output dict the mock tool should return.
    If the tool has an ``_error`` key, returns ``{"_error": "..."}``
    so the caller can raise a ToolException.
    Returns None if the scenario has no fixture for the given tool.

    Args:
        scenario_name: The scenario filename (without .yaml extension).
        tool_name: The tool name to look up.

    Returns:
        Fixture dict, error dict, or None.
    """
    scenario = load_scenario(scenario_name)
    tools = scenario.get("tools") or {}
    tool_data = tools.get(tool_name)
    if tool_data is None:
        return None
    if "_error" in tool_data:
        return tool_data
    return tool_data.get("_default", tool_data)

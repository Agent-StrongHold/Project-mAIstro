"""I4: dangerous-command, tool, and host-path conformance.

The expected cases come from the independently governed security oracle, not
from maistro-core's pattern declarations. This distinction makes deletion and
weakening mutations observable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import maistro.security.dangerous_tools as dangerous_tools


_ORACLE_PATH = Path(__file__).parents[1] / "fixtures" / "security_oracle.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text(encoding="utf-8"))
DANGEROUS_COMMANDS = _ORACLE["dangerous_commands"]
SAFE_COMMANDS = _ORACLE["safe_commands"]
DANGEROUS_TOOLS = _ORACLE["dangerous_tools"]
SAFE_TOOLS = _ORACLE["safe_tools"]
BLOCKED_PATHS = _ORACLE["blocked_paths"]
ALLOWED_PATHS = _ORACLE["allowed_paths"]


@pytest.mark.parametrize("case", DANGEROUS_COMMANDS, ids=lambda case: case["id"])
def test_dangerous_commands_match_oracle(case: dict[str, object]) -> None:
    """Every governed adversarial example is denied with the expected evidence."""
    matches = dangerous_tools.is_dangerous_command(case["input"])
    assert len(matches) == case["expected_matches"], case["id"]


@given(command=st.sampled_from([case["input"] for case in DANGEROUS_COMMANDS]))
@settings(max_examples=100)
def test_dangerous_command_property(command: str) -> None:
    """Property exploration repeatedly exercises the independent deny oracle."""
    assert dangerous_tools.is_dangerous_command(command)


@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_safe_commands_match_oracle(command: str) -> None:
    assert dangerous_tools.is_dangerous_command(command) == []


def test_command_rule_deletion_cannot_pass() -> None:
    """A runtime deletion of any detector changes an independently measured case."""
    original = dangerous_tools.DANGEROUS_COMMAND_PATTERNS
    assert len(original) == 22

    for index in range(len(original)):
        mutated = original[:index] + original[index + 1 :]
        dangerous_tools.DANGEROUS_COMMAND_PATTERNS = mutated
        try:
            changed = any(
                len(dangerous_tools.is_dangerous_command(case["input"])) != case["expected_matches"]
                for case in DANGEROUS_COMMANDS
            )
            assert changed, f"deleting detector {index} did not change the oracle"
        finally:
            dangerous_tools.DANGEROUS_COMMAND_PATTERNS = original


@pytest.mark.parametrize("tool", DANGEROUS_TOOLS)
def test_dangerous_tool_oracle(tool: str) -> None:
    assert dangerous_tools.is_dangerous_tool(tool)
    assert dangerous_tools.is_dangerous_tool(tool.upper())


@pytest.mark.parametrize("tool", SAFE_TOOLS)
def test_safe_tool_oracle(tool: str) -> None:
    assert not dangerous_tools.is_dangerous_tool(tool)


@pytest.mark.parametrize("path", BLOCKED_PATHS)
def test_blocked_path_oracle(path: str) -> None:
    assert dangerous_tools.is_blocked_path(path)
    assert dangerous_tools.is_blocked_path(f"{path}/child")


@pytest.mark.parametrize("path", ALLOWED_PATHS)
def test_allowed_path_oracle(path: str) -> None:
    assert not dangerous_tools.is_blocked_path(path)

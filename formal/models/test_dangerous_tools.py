"""I4: dangerous-command, tool, and host-path conformance.

The expected cases come from the independently governed security oracle, not
from maistro-core's pattern declarations. This distinction makes deletion and
weakening mutations observable.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.tools.sandbox.microvm import MicroVMSandbox, MicroVMRunSpec

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


# Benign contexts that must not launder a governed dangerous command into a
# permitted one. The detector rules are unanchored, so a composition preserves
# every effective match; a shadowing mutation (an allowlist or safe-prefix short
# circuit evaluated before the deny rules) drops them and fails these cases.
_COMPOSITIONS = {
    "after-echo": "echo setup; {command}",
    "after-and": "cd /tmp && {command}",
    "before-comment": "{command} # trailing note",
}


@pytest.mark.parametrize("case", DANGEROUS_COMMANDS, ids=lambda case: case["id"])
@pytest.mark.parametrize("label", sorted(_COMPOSITIONS))
def test_composition_cannot_launder_dangerous_command(case: dict[str, object], label: str) -> None:
    """A dangerous command stays denied inside a benign surrounding context."""
    composed = _COMPOSITIONS[label].format(command=case["input"])
    assert dangerous_tools.is_dangerous_command(composed), (label, case["id"])


@pytest.mark.parametrize("case", DANGEROUS_COMMANDS, ids=lambda case: case["id"])
def test_enforcement_path_refuses_oracle_commands(case: dict[str, object]) -> None:
    """The production sandbox executor refuses every governed dangerous command.

    This drives `MicroVMSandbox.exec` — the SPEC-190 `SandboxExec` seam — rather
    than calling `is_dangerous_command` directly, so a detector that became
    unreachable from production (the executor dropping its deny check) is a
    measured failure: the sentinel launcher would run and this model would
    observe the command executing.
    """
    executed: list[str] = []

    async def sentinel_launcher(spec: MicroVMRunSpec) -> tuple[int, str]:
        executed.append(spec.command)
        return 0, f"executed: {spec.command}"

    sandbox = MicroVMSandbox(sentinel_launcher, workspace="/tmp/maistro-workspace")
    exit_code, output = asyncio.run(sandbox.exec(str(case["input"])))

    assert executed == [], f"dangerous command reached the microVM launcher: {case['id']}"
    assert exit_code != 0, case["id"]
    assert "blocked" in output.lower(), case["id"]


@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_enforcement_path_runs_oracle_safe_commands(command: str) -> None:
    """The deny path is not a shadow that blocks every command: governed benign
    commands still reach the launcher."""
    executed: list[str] = []

    async def recording_launcher(spec: MicroVMRunSpec) -> tuple[int, str]:
        executed.append(spec.command)
        return 0, f"ran: {spec.command}"

    sandbox = MicroVMSandbox(recording_launcher, workspace="/tmp/maistro-workspace")
    exit_code, output = asyncio.run(sandbox.exec(command))

    assert executed == [command]
    assert (exit_code, output) == (0, f"ran: {command}")


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

"""The command tool is structured argv, never model-authored shell text."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from maistro_bootstrap.builders.agent_loop import _dispatch_tool, _make_sandbox_tools
from maistro_bootstrap.builders.sandbox import SandboxedShell
from maistro_bootstrap.builders.session import BuilderSession


class _Sandbox:
    def __init__(self) -> None:
        self.argv: list[list[str]] = []

    def run_argv(self, argv: list[str], *, timeout: int = 30) -> str:
        self.argv.append(argv)
        return f"ran {timeout}"

    def read_file(self, _path: str) -> str:
        raise AssertionError("not a read")

    def write_file(self, _path: str, _content: str) -> None:
        raise AssertionError("not a write")

    def edit_file(self, _path: str, _old: str, _new: str) -> str:
        raise AssertionError("not an edit")

    def diff(self) -> str:
        raise AssertionError("not a diff")

    def search(self, _pattern: str, *, glob: str = "**/*.py") -> list[str]:
        raise AssertionError("not a search")


class _Session:
    def __init__(self, sandbox: _Sandbox) -> None:
        self.sandbox = sandbox


def test_run_command_schema_requires_argv_and_has_no_cmd_string() -> None:
    definitions = _make_sandbox_tools(cast(BuilderSession, _Session(_Sandbox())))
    command = next(item for item in definitions if item["name"] == "run_command")
    schema = command["input_schema"]
    assert schema["required"] == ["argv"]
    assert "cmd" not in schema["properties"]
    assert schema["properties"]["argv"]["type"] == "array"


def test_run_command_rejects_raw_command_and_dispatches_argv_without_shell() -> None:
    sandbox = _Sandbox()
    session = cast(BuilderSession, _Session(sandbox))

    rejected = _dispatch_tool(session, "run_command", {"cmd": "echo safe"})
    assert "requires a non-empty string argv" in rejected
    assert sandbox.argv == []

    result = _dispatch_tool(session, "run_command", {"argv": ["echo", "safe"], "timeout": 7})
    assert result == "ran 7"
    assert sandbox.argv == [["echo", "safe"]]


def test_run_command_rejects_shell_metacharacter_tokens() -> None:
    sandbox = _Sandbox()
    result = _dispatch_tool(
        cast(BuilderSession, _Session(sandbox)),
        "run_command",
        {"argv": ["echo", "safe", ";", "touch", "owned"]},
    )
    assert "metacharacters" in result
    assert sandbox.argv == []


# ---------------------------------------------------------------------------
# Real-sandbox executable boundary (#57)
# ---------------------------------------------------------------------------
#
# The recording stubs above pin the schema/argv plumbing, but a stub's
# run_argv accepts everything — exactly the assumption that let the escape
# through. These tests dispatch through the REAL SandboxedShell so the
# model-facing run_command path is pinned to the executor's boundary.


@pytest.mark.skipif(os.name != "posix", reason="/bin/touch path is POSIX-specific")
def test_run_command_model_argv_cannot_execute_outside_root(tmp_path: Path) -> None:
    """Model-authored argv[0] naming an outside-root executable is refused.

    run_command forwards model-authored argv to sandbox.run_argv; when the
    sandbox validated argv[1:] only, argv[0]="/bin/touch" executed the real
    binary. The argument here is deliberately a safe relative path, so the
    ONLY escape is the executable token itself. It must come back as a tool
    error and no subprocess may run — proven by the file /bin/touch would
    create inside the root never appearing.
    """
    session = BuilderSession(sandbox=SandboxedShell(tmp_path))
    result = _dispatch_tool(session, "run_command", {"argv": ["/bin/touch", "escaped.txt"]})
    assert "Path escape detected" in result
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.skipif(os.name != "posix", reason="bare echo is POSIX-specific")
def test_run_command_still_dispatches_bare_executable_names(tmp_path: Path) -> None:
    """The executable boundary must not over-block the legitimate shape."""
    session = BuilderSession(sandbox=SandboxedShell(tmp_path))
    result = _dispatch_tool(session, "run_command", {"argv": ["echo", "dispatch-ok"]})
    assert "dispatch-ok" in result

"""The command tool is structured argv, never model-authored shell text."""

from __future__ import annotations

from typing import cast

from maistro_bootstrap.builders.agent_loop import _dispatch_tool, _make_sandbox_tools
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

"""run_tests argument policy (#811).

`run_tests` is a *safe* tool: it dispatches before the general `run_command`
approval gate, on the theory that its argv is fixed and shell-free. The
`args` input broke that theory — it was appended verbatim
(``argv += extra.split()``), so ``-p evil_plugin`` made pytest import a
module the model had just written into the sandbox. The "safe" classification
must mean the model can only select tests and shape output, never widen what
pytest imports.

These tests pin both sides of that contract: plugin/config-loading vectors
never reach the executor, and the ordinary selection/verbosity flags builders
rely on still arrive byte-for-byte.
"""

from __future__ import annotations

from typing import cast

import pytest

from maistro_bootstrap.builders.agent_loop import (
    _dispatch_tool,
    _validate_pytest_args,
)
from maistro_bootstrap.builders.errors import BlockedCommandError
from maistro_bootstrap.builders.session import BuilderSession


class _RecordingSandbox:
    """BuilderSandbox stand-in whose only job is to record run_argv calls.

    If a rejected invocation reaches `run_argv`, it reached the subprocess
    boundary — that is exactly what these tests exist to prevent.
    """

    def __init__(self) -> None:
        self.argv_calls: list[list[str]] = []

    def run_argv(self, argv: list[str], *, timeout: int = 30) -> str:
        self.argv_calls.append(list(argv))
        return "ok"

    # Everything below the protocol surface: this sandbox never runs.
    def read_file(self, path: str) -> str:
        raise AssertionError("unexpected read_file")

    def write_file(self, path: str, content: str) -> None:
        raise AssertionError("unexpected write_file")

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        raise AssertionError("unexpected edit_file")

    def run_command(self, cmd: str, *, timeout: int = 30) -> str:
        raise AssertionError("unexpected run_command")

    def diff(self) -> str:
        raise AssertionError("unexpected diff")

    def search(self, pattern: str, *, glob: str = "**/*.py") -> list[str]:
        raise AssertionError("unexpected search")


class _SandboxSession:
    """Just enough BuilderSession for _dispatch_tool: a sandbox, nothing else."""

    def __init__(self, sandbox: _RecordingSandbox) -> None:
        self.sandbox = sandbox

    def add_assistant(self, content: str) -> None:
        raise AssertionError("unexpected add_assistant")


def _run_tests(args: str) -> tuple[_RecordingSandbox, str]:
    sandbox = _RecordingSandbox()
    result = _dispatch_tool(
        cast(BuilderSession, _SandboxSession(sandbox)), "run_tests", {"args": args}
    )
    return sandbox, result


# --- the hole (#811): extension-loading vectors never reach the executor ----
#
# Each vector below is a distinct way to make pytest import or reconfigure
# with code the model chose. None may reach sandbox.run_argv.


@pytest.mark.parametrize(
    "bad_args",
    [
        # The reported vector: -p makes pytest import a module by name.
        "-p evil_plugin",
        "-pno:terminal",
        "-pevil_plugin",  # glued short form
        "--plugin evil_plugin",  # equivalent long spelling
        # Config file loading: addopts/plugins ini keys re-enter the same hole.
        "-c evil.ini",
        "--config-file=evil.ini",
        # Import-path mutation: positionals become importable sys.path modules.
        "--pyargs",
        # Ini rewrite at runtime can smuggle addopts/plugins back in.
        "-o addopts=-p evil_plugin",
        "--override-ini=plugins=evil_plugin",
        "--import-mode=importlib",
    ],
)
def test_extension_loading_args_never_reach_the_executor(bad_args: str) -> None:
    sandbox, result = _run_tests(bad_args)

    # Nothing was dispatched — not even a sanitized argv.
    assert sandbox.argv_calls == []
    # The refusal surfaces to the model as a tool error naming the token.
    assert result.startswith("[tool error]")
    assert "not allowed" in result or "missing its value" in result


def test_rejection_is_all_or_nothing() -> None:
    """A safe flag next to a poison flag must not partially dispatch."""
    sandbox, _ = _run_tests("-q -p evil_plugin")

    assert sandbox.argv_calls == []


def test_rejection_names_the_offending_token() -> None:
    with pytest.raises(BlockedCommandError, match=r"-p"):
        _validate_pytest_args("-q -p evil_plugin")


# --- parity: ordinary flags reach the executor byte-for-byte ----------------
#
# The flags builders actually use today (the tool's own description says
# '-k my_test -q'; the shell-path suite's allowlist shows
# '-x --maxfail=1' and '--ignore=...' conventions) must keep working.


@pytest.mark.parametrize(
    ("args", "expected_extra"),
    [
        ("", []),
        ("-k my_test -q", ["-k", "my_test", "-q"]),
        ("tests/unit -x --maxfail=1", ["tests/unit", "-x", "--maxfail=1"]),
        ("--maxfail 1 tests/unit", ["--maxfail", "1", "tests/unit"]),
        ("-m 'not slow' -v", ["-m", "not slow", "-v"]),
        ("-m smoke", ["-m", "smoke"]),
        ("--tb=short --ignore=tests/benchmarks", ["--tb=short", "--ignore=tests/benchmarks"]),
        ("--tb long -q", ["--tb", "long", "-q"]),
        ("tests/test_x.py::test_y --lf", ["tests/test_x.py::test_y", "--lf"]),
        ("--last-failed --failed-first", ["--last-failed", "--failed-first"]),
        ("-s -vv tests/", ["-s", "-vv", "tests/"]),
        ("--deselect tests/a.py::test_b tests/", ["--deselect", "tests/a.py::test_b", "tests/"]),
        ("-kglued --co", ["-kglued", "--co"]),
        ("--collect-only --strict-markers", ["--collect-only", "--strict-markers"]),
        ("-rA tests/unit", ["-rA", "tests/unit"]),
    ],
)
def test_supported_selection_flags_reach_the_executor_verbatim(
    args: str, expected_extra: list[str]
) -> None:
    sandbox, result = _run_tests(args)

    assert sandbox.argv_calls == [["python", "-m", "pytest", *expected_extra]]
    assert result == "ok"


# --- parsed argv semantics, not substring matching ---------------------------


def test_node_id_containing_the_p_substring_is_not_a_flag() -> None:
    """A naive ``"-p" in args`` check would reject this node id outright."""
    sandbox, _ = _run_tests("tests/test-plugin-flag.py::test_dash_p -q")

    assert sandbox.argv_calls == [
        ["python", "-m", "pytest", "tests/test-plugin-flag.py::test_dash_p", "-q"]
    ]


def test_quoted_expression_parses_to_one_argv_token() -> None:
    """shlex semantics: a quoted -k expression is one token, not four words."""
    sandbox, _ = _run_tests("-k 'parse or serialize' -q")

    assert sandbox.argv_calls == [["python", "-m", "pytest", "-k", "parse or serialize", "-q"]]


def test_a_value_token_starting_with_dash_is_consumed_not_flagged() -> None:
    """``-k -p`` parses as the expression "-p", not as the -p plugin flag."""
    tokens = _validate_pytest_args("-k -p")

    assert tokens == ["-k", "-p"]


# --- malformed input is rejected, never guessed at ---------------------------


@pytest.mark.parametrize(
    "bad_args",
    [
        "-k",  # value flag with no value
        "--maxfail",  # long value flag with no value
        "--maxfail=",  # glued long form with an empty value
        "--unknown-flag",  # not in the allowlist at all
        "-vx",  # boolean cluster (unsupported, conservative reject)
        "-W error",  # warning-control flag: not selection/verbosity
    ],
)
def test_malformed_or_unknown_args_are_rejected(bad_args: str) -> None:
    with pytest.raises(BlockedCommandError):
        _validate_pytest_args(bad_args)


def test_unparseable_args_are_rejected_not_guessed() -> None:
    with pytest.raises(BlockedCommandError, match="Unparseable"):
        _validate_pytest_args('-k "unclosed quote')


def test_missing_or_null_args_dispatch_the_plain_invocation() -> None:
    """Old callers omit `args` (or send null); the no-arg run still works."""
    for inputs in ({}, {"args": None}):
        sandbox = _RecordingSandbox()
        result = _dispatch_tool(cast(BuilderSession, _SandboxSession(sandbox)), "run_tests", inputs)

        assert sandbox.argv_calls == [["python", "-m", "pytest"]]
        assert result == "ok"

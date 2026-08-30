"""No test inherits the merge-group event it did not ask for.

`check_ac_state_impl.in_merge_group()` reads `GITHUB_EVENT_NAME`, and a
merge-group CI job exports that to pytest itself. A ratchet test that does not
pin the event therefore runs against #620's carve-out inside the queue and
against the ordinary contract everywhere else -- green on the pull request, red
where it decides the merge, which is the worst place to find out.

`tests/conftest.py` pins a neutral default for this whole root. These hold that
it is actually neutral, that a test can still opt in, and -- the one that would
have caught the miss -- that every module driving the ratchet is covered, rather
than a list of module names that cannot know about the next one.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

#: Names that reach the carve-out. `ratchet` consults `in_merge_group`, and
#: `main` reaches it through `ratchet`.
RATCHET_CALLS = frozenset({"ratchet", "in_merge_group"})

#: The autouse fixture in `tests/conftest.py` that pins the event.
FIXTURE = "_default_ac_state_ratchet_event"


def _calls_the_ratchet(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in RATCHET_CALLS:
            return True
    return False


def test_the_neutral_default_reaches_this_module_too() -> None:
    """The miss was a module the allowlist did not name. This is such a module."""
    assert os.environ["GITHUB_EVENT_NAME"] == "pull_request"


def test_a_test_can_still_opt_into_merge_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is a floor: a test body runs after the fixture and wins."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")

    assert os.environ["GITHUB_EVENT_NAME"] == "merge_group"


def _fixture(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"tests/conftest.py no longer defines {name}")


def _sets_the_event(node: ast.AST) -> bool:
    """True for a `monkeypatch.setenv("GITHUB_EVENT_NAME", ...)` call."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute) or func.attr != "setenv":
            continue
        first = child.args[0] if child.args else None
        if isinstance(first, ast.Constant) and first.value == "GITHUB_EVENT_NAME":
            return True
    return False


def test_the_neutral_default_is_structurally_unconditional() -> None:
    """The property the old filename allowlist could not hold.

    Not "the one spelling this PR removed is absent" -- an equivalent
    allowlist written any other way (`request.node.path.name in RATCHET_TESTS`)
    would pass a substring check while reintroducing the exact defect. So this
    reads the fixture's syntax tree: the `setenv` must be reached
    unconditionally, whatever the condition would have been spelled.
    """
    tree = ast.parse((TESTS / "conftest.py").read_text(encoding="utf-8"))
    fixture = _fixture(tree, FIXTURE)

    assert _sets_the_event(fixture), f"{FIXTURE} no longer pins GITHUB_EVENT_NAME"
    guarded = [
        branch
        for branch in ast.walk(fixture)
        if isinstance(branch, ast.If) and _sets_the_event(branch)
    ]
    assert not guarded, (
        f"{FIXTURE} pins GITHUB_EVENT_NAME inside a conditional again, so it can "
        "miss a module the way the filename allowlist missed test_ac_state_notes.py"
    )


def test_every_module_that_drives_the_ratchet_is_named_by_the_search() -> None:
    """The structural check above is only worth anything if drivers exist.

    A typo in `RATCHET_CALLS`, or the suites moving, would leave the check
    passing over an empty set. Both known ratchet suites must be found.
    """
    drivers = {
        path.relative_to(ROOT).as_posix()
        for path in TESTS.rglob("test_*.py")
        if _calls_the_ratchet(path)
    }

    assert "tests/test_ac_state_notes.py" in drivers
    assert "tests/test_check_ac_state_ratchet.py" in drivers

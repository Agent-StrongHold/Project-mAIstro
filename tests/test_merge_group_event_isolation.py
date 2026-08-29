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


def test_every_module_that_drives_the_ratchet_is_covered() -> None:
    """The property the old filename allowlist could not hold.

    Not "these two modules are listed" -- that is what missed
    `test_ac_state_notes.py`. Every module in this root that calls into the
    ratchet gets the neutral default, because the default is unconditional.
    """
    drivers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in TESTS.rglob("test_*.py")
        if _calls_the_ratchet(path)
    )

    assert drivers, "expected at least the ratchet suites to be found"
    conftest = (TESTS / "conftest.py").read_text(encoding="utf-8")
    assert "if request.node.nodeid.startswith(" not in conftest, (
        f"the neutral default is conditional again, so it can miss a module: {', '.join(drivers)}"
    )

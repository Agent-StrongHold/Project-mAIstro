"""Executable evidence for the M1 no-new-islands freeze (#460)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix(*subsystems: str) -> str:
    rows = "\n".join(f"| {name} | `example.{index}` |" for index, name in enumerate(subsystems))
    return f"# matrix\n\n<!-- matrix:ownership -->\n| Subsystem | Modules |\n|---|---|\n{rows}\n"


def test_new_subsystem_is_rejected_without_exception() -> None:
    checker = _module()
    current = _matrix("Canonical", "New island")
    base = _matrix("Canonical")

    failures = checker.check(current, base, exception=False)

    assert len(failures) == 1
    assert "New island" in failures[0]
    assert "m1-convergence-exception" in failures[0]


def test_explicit_exception_allows_reviewed_new_subsystem() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical", "Reviewed extension"),
            _matrix("Canonical"),
            exception=True,
        )
        == []
    )


def test_shrinking_the_island_set_is_always_allowed() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical"),
            _matrix("Canonical", "Legacy island"),
            exception=False,
        )
        == []
    )


def test_live_pull_request_does_not_add_unapproved_subsystem() -> None:
    """Make the freeze a real PR gate, not merely a unit-tested policy helper."""
    base_ref = os.environ.get("GITHUB_BASE_REF")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not base_ref or not event_path:
        # Local/push runs still execute the three policy tests above. The live
        # comparison is meaningful only when Actions has checked out a PR and
        # fetched its base ref.
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    labels = {
        item.get("name", "")
        for item in event.get("pull_request", {}).get("labels", [])
        if isinstance(item, dict)
    }
    # `actions/checkout` clones one commit deep, so `origin/<base>` does not
    # exist in the `test` job and the checker died on `invalid object name`
    # (#497). Fetch it here rather than skipping when it is absent: guarding on
    # the ref's presence would turn a gate that never runs into a gate that
    # looks like it passed, which is the failure this whole freeze exists to
    # prevent one level up.
    base = _fetched_base(base_ref)
    command = [sys.executable, str(CHECKER), "--base", base]
    if "m1-convergence-exception" in labels:
        command.append("--exception")

    subprocess.run(command, cwd=ROOT, check=True)


def _fetched_base(base_ref: str) -> str:
    """A revision naming the PR's base, fetched if the shallow clone lacks it.

    Returns whatever revision the checker should compare against: the existing
    remote-tracking ref when the clone is complete enough to have one, and the
    freshly fetched `FETCH_HEAD` otherwise.
    """
    remote_ref = f"origin/{base_ref}"
    if _rev_exists(remote_ref):
        return remote_ref

    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return "FETCH_HEAD"


def _rev_exists(revision: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


class TestTheBaseRevisionIsResolvedNotAssumed:
    """`actions/checkout` clones one commit deep, so the base ref the live
    comparison needs is simply absent in the `test` job (#497). These cover the
    resolution, because the alternative fix -- skipping when it is missing --
    would turn a gate that never runs into one that looks like it passed.
    """

    def test_an_existing_remote_ref_is_used_as_is(self, monkeypatch) -> None:
        """No fetch when the clone already has it: a network round trip on
        every local run would be a cost paid for nothing."""
        fetched: list[list[str]] = []
        module = sys.modules[__name__]
        monkeypatch.setattr(module, "_rev_exists", lambda revision: True)
        monkeypatch.setattr(module, "subprocess", _FakeSubprocess(fetched))

        assert module._fetched_base("develop") == "origin/develop"
        assert fetched == []

    def test_a_missing_ref_is_fetched_and_compared_against_FETCH_HEAD(self, monkeypatch) -> None:
        fetched: list[list[str]] = []
        module = sys.modules[__name__]
        monkeypatch.setattr(module, "_rev_exists", lambda revision: False)
        monkeypatch.setattr(module, "subprocess", _FakeSubprocess(fetched))

        assert module._fetched_base("develop") == "FETCH_HEAD"
        assert fetched == [["git", "fetch", "--no-tags", "--depth=1", "origin", "develop"]]

    def test_a_remote_ref_this_clone_has_is_returned_without_fetching(self) -> None:
        """Against the real clone, on the branch that needs no network.

        Never `_fetched_base("HEAD")`: `origin/HEAD` is absent in plenty of
        checkouts, so that would send this unconditional test down the fetch
        path and fail the whole root suite in any clone with no `origin` or an
        unreachable one -- while the live PR gate it belongs to is not even
        active. So it names a remote ref this clone actually has, and skips
        when there is none to name.
        """
        listed = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--count=1",
                "--format=%(refname:strip=3)",
                "refs/remotes/origin",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        base_ref = listed.stdout.strip()
        if not base_ref:
            pytest.skip("this clone has no origin refs, so there is no no-fetch case to cover")

        assert _fetched_base(base_ref) == f"origin/{base_ref}"
        assert _rev_exists(f"origin/{base_ref}")


class _FakeSubprocess:
    """Records `run` calls instead of making them."""

    def __init__(self, calls: list[list[str]]) -> None:
        self._calls = calls

    def run(self, command: list[str], **_kwargs: object) -> object:
        self._calls.append(list(command))
        return object()

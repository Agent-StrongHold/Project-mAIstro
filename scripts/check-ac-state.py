#!/usr/bin/env python3
"""Coordinate AC-state review and merge-time regression checks (#620).

The implementation module owns measurement, branch-note exactness, and the
per-change mandate. This stable entry point adds the one question a synthetic
merge has that a reviewed branch does not: did the combination preserve the
*actual measured state* of the base it is about to replace?

Pull requests still use the branch-note fold exactly as before. Merge groups and
protected-branch pushes additionally measure their immutable base revision in a
detached worktree and compare the candidate against that measurement. This is
what makes an improvement that emerges only from combining two independently
reviewed PRs durable without asking either author to pre-bank a number that did
not exist when their branch was reviewed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_ac_state_impl as _impl  # noqa: E402


class _ImplementationSurface(types.ModuleType):
    """This module's public surface *is* the implementation's, not a copy of it.

    Unit tests and local callers load `scripts/check-ac-state.py` by path and
    reach helpers such as `ratchet` through it, so that surface has to stay.
    Copying `vars(_impl)` into these globals looked like a way to keep it and
    was not: a re-exported function still closes over `check_ac_state_impl`'s
    globals, so `monkeypatch.setattr(check_ac_state, "SPEC_DIR", tmp_path)`
    rebound a name nothing ever read and the patched behaviour never happened.

    Five of this gate's own tests went red the moment the split landed, and
    they were right to. A gate whose documented surface can be patched without
    changing the behaviour behind it is the same shape of defect the ladder in
    `check_ac_state_impl` exists to catch: a name that looks like the thing and
    is not wired to it.

    Reads fall through to the implementation for anything this module does not
    define itself; writes land on the implementation for the names it owns, so
    a caller patching the entry point patches the code that runs.
    """

    def __getattr__(self, name: str) -> Any:
        # Only reached when this module's own namespace has no such name.
        try:
            return getattr(_impl, name)
        except AttributeError:
            raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        if not name.startswith("__") and name not in self.__dict__ and hasattr(_impl, name):
            setattr(_impl, name, value)
            return
        object.__setattr__(self, name, value)


# Module-level `def` and assignment below write straight to this module's
# `__dict__`, so they keep their own names; only attribute access from outside
# is routed.
sys.modules[__name__].__class__ = _ImplementationSurface

_PROTECTED_PUSH_REFS = {
    "refs/heads/develop",
    "refs/heads/integration",
    "refs/heads/main",
}
_BASE_MEASUREMENT = "AC_STATE_BASE_MEASUREMENT"


def _event_payload() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _protected_push() -> bool:
    return (
        os.environ.get("GITHUB_EVENT_NAME") == "push"
        and os.environ.get("GITHUB_REF") in _PROTECTED_PUSH_REFS
    )


def _needs_actual_base() -> bool:
    return os.environ.get("GITHUB_EVENT_NAME") == "merge_group" or _protected_push()


def _actual_base_revision() -> str | None:
    """The immutable revision this synthetic/protected result replaces."""
    event = os.environ.get("GITHUB_EVENT_NAME")
    payload = _event_payload()
    if event == "merge_group":
        env_base = os.environ.get("MANDATE_BASE_SHA")
        if env_base:
            return env_base
        merge_group = payload.get("merge_group")
        if isinstance(merge_group, dict):
            base = merge_group.get("base_sha")
            return base if isinstance(base, str) and base else None
        return None
    if _protected_push():
        before = payload.get("before")
        return before if isinstance(before, str) and before and set(before) != {"0"} else None
    return None


def _out_path(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--out" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if arg.startswith("--out="):
            return Path(arg.split("=", 1)[1])
    return _impl.DEFAULT_OUT


def _without_ratchet(argv: list[str]) -> list[str]:
    """Protected pushes use actual-parent regression, not review-time exactness."""
    return [arg for arg in argv if arg != "--ratchet"]


def _measure_base(base_rev: str, report: Path) -> str | None:
    """Measure `base_rev` with its own code and dependencies, fail closed."""
    root = _impl.ROOT
    with tempfile.TemporaryDirectory(prefix="maistro-ac-base-") as tmp:
        worktree = Path(tmp) / "tree"
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), base_rev],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if added.returncode != 0:
            return f"could not create base worktree for {base_rev}: {added.stderr.strip()}"
        try:
            env = {
                **os.environ,
                _BASE_MEASUREMENT: "1",
                # A base measurement asks only what the tree proves. It is not
                # itself a merge-group policy run, and its unit tests must not
                # inherit the outer job's event classification.
                "GITHUB_EVENT_NAME": "pull_request",
            }
            measured = subprocess.run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(worktree),
                    "--locked",
                    "--all-extras",
                    "python",
                    "scripts/check-ac-state.py",
                    "--out",
                    str(report),
                    "--run-tests",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
            if measured.returncode != 0 or not report.is_file():
                tail = (measured.stdout + measured.stderr)[-4000:]
                return f"could not measure actual AC-state base {base_rev}:\n{tail}"
            return None
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )


def _report_totals(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("measured") is not True:
        raise ValueError(f"{path} is not a --run-tests AC-state measurement")
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"{path} records no totals")
    missing = [name for name in (*_impl.RATCHETED, *_impl.FLOORED) if name not in totals]
    if missing:
        raise ValueError(f"{path} is missing bounded counters: {', '.join(missing)}")
    return totals


def _actual_base_regressions(base: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Only worse-than-base movement; improvement becomes the next base itself."""
    regressions, _improvements = _impl._compare(base, candidate)
    return regressions


def _guard_actual_base(base_report: Path, candidate_report: Path, base_rev: str) -> int:
    try:
        base = _report_totals(base_report)
        candidate = _report_totals(candidate_report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: actual-base AC-state comparison could not be read: {exc}")
        return 1
    regressions = _actual_base_regressions(base, candidate)
    if regressions:
        print(f"FAIL: AC-state regressed from the actual measured base {base_rev}\n")
        for line in regressions:
            print(f"  - {line}")
        print(
            "\nThis comparison is independent of branch notes: a merge-group-only "
            "improvement becomes part of the next base measurement, so a later "
            "PR cannot spend it even when no author could have pre-banked it."
        )
        return 1
    print(
        f"OK: candidate preserves the actual measured AC-state of base {base_rev}; "
        "any improvement becomes the next base measurement."
    )
    return 0


def main(argv: list[str]) -> int:
    # The detached base invokes the same public path. Do not recursively measure
    # another base from inside that measurement.
    if os.environ.get(_BASE_MEASUREMENT) == "1" or not _needs_actual_base():
        return _impl.main(argv)

    base_rev = _actual_base_revision()
    if not base_rev:
        print("FAIL: this run requires an immutable AC-state base revision, but none was available")
        return 1

    with tempfile.TemporaryDirectory(prefix="maistro-ac-guard-") as tmp:
        base_report = Path(tmp) / "base.json"
        error = _measure_base(base_rev, base_report)
        if error is not None:
            print(f"FAIL: {error}")
            return 1

        # A protected-branch push has no author-side review question left to
        # answer. Its invariant is simply no regression from the actual parent.
        # Merge groups still run the ordinary ratchet/mandate as well, which
        # preserves the reviewed branch's exact target and touched-criterion
        # contract while the actual-base guard preserves emergent combination
        # improvements for the next PR.
        delegated = _without_ratchet(argv) if _protected_push() else argv
        code = _impl.main(delegated)
        if code:
            return code
        candidate_report = _out_path(delegated)
        return _guard_actual_base(base_report, candidate_report, base_rev)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

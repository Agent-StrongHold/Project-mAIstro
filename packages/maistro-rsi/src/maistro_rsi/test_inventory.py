"""Protected test inventory: what pytest collects, base vs candidate (#306).

Per-file TDD scoring floors at zero and skips deleted files, so a candidate can
delete a failing test, make the remaining suite green, and receive no explicit
veto for shrinking the oracle. This module measures that shrink directly: it
collects the candidate's suite with pytest itself (``--collect-only -q``, never
a test run) and diffs the resulting node IDs against the baseline's.

The oracle is the **node-ID set**, not a count — a candidate that adds 3 tests
while deleting 2 keeps the count growing while the 2 deleted identities (and the
regressions they exposed) are gone. Stable identity is the full node ID
(``file::class::name``), so a rename is simply the old ID deleted plus a new one
added, and it fails exactly like a deletion.

Three hiding mechanisms are covered by construction:

- **deletion/rename** — the ID vanishes from the collected set;
- **skip markers** — the ID still collects but is deselected by
  ``-m "not skip and not skipif"``; a differential second collection (the
  "servable" pass) removes it from the protected set, so disabling an existing
  test with ``@pytest.mark.skip``/``skipif`` reads as a deletion;
- **config-based deselection** — an edited ``pytest.ini``/``pyproject.toml``/
  ``conftest.py`` that shrinks collection shows up as deleted IDs, and the
  config change itself is flagged by :func:`changed_config_files` so the gate
  can treat "config touched + any shrink" as presumed hiding.

Collection failure is itself a failure of the inventory: a suite that cannot be
collected cannot be verified, so :class:`InventoryResult` carries
``collection_ok`` and the gate fails closed on it (#307 doctrine).

Collection runs ``sys.executable -m pytest`` — the same invocation the
``_uncollectable_tests`` gate already uses — rather than ``uv run pytest``: the
harness interpreter is the workspace venv either way, and a bare ``uv run`` in a
candidate worktree would resync a fresh virtualenv per candidate (and outright
fail in the bare fixture trees this module is tested against). Behind the same
credential boundary as every other candidate-importing run (#78): collection
imports the candidate's ``conftest`` and plugins, so it gets the minimal base
environment, never ambient credentials.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from maistro_evolve._candidate_env import candidate_env

# Whole-suite collection (not a single file) bounded for the same reason the
# other gates bound their tool runs: an unbounded collect wedges the cycle.
_COLLECT_TIMEOUT = 300

# The differential skip pass: IDs that vanish under this marker filter are
# skip-gated (deselected at run time), so they don't count as protected.
_SKIP_FILTER = ("-m", "not skip and not skipif")

# Files whose change can hide inventory reductions without deleting a test
# file: pytest reads its config from any of these (first found wins for the
# ini ones; conftest.py applies per directory), so editing one can deselect,
# re-root, or filter the collected set. Matched by basename at any depth —
# a nested tests/pytest.ini or tests/conftest.py is exactly as load-bearing.
_TEST_CONFIG_BASENAMES = frozenset(
    {
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "tox.ini",
        "conftest.py",
    }
)


def test_config_paths() -> frozenset[str]:
    """Basenames of the files whose change can hide inventory reductions."""
    return _TEST_CONFIG_BASENAMES


def changed_config_files(changed: list[str]) -> list[str]:
    """Which of ``changed`` (repo-relative paths) touch test configuration."""
    names = test_config_paths()
    return [f for f in changed if f.replace("\\", "/").rsplit("/", 1)[-1] in names]


def _parse_node_ids(stdout: str) -> set[str]:
    """Node IDs from ``--collect-only -q`` output: one ID per line, each
    containing ``::``. Error/summary lines never contain ``::`` before their
    first space (traceback lines use single colons: ``file.py:12: in f``), and
    the path part of a real ID contains no space, which filters the rest."""
    ids: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if "::" not in stripped or stripped.startswith(("=", "!", "E ")):
            continue
        if " " in stripped.split("::", 1)[0]:
            continue
        ids.add(stripped)
    return ids


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = [ln.strip() for ln in out.strip().splitlines()[-8:] if ln.strip()]
    return " | ".join(tail)[:400]


def _collect(
    root: Path, pytest_args: list[str], extra: tuple[str, ...], timeout: int
) -> tuple[set[str], int, str]:
    """Run one ``--collect-only -q`` pass; return (ids, returncode, error tail)."""
    argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra, *pytest_args]
    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=candidate_env(),
        )
    except subprocess.TimeoutExpired:
        return set(), 124, f"collection timed out after {timeout}s"
    except OSError as exc:
        return set(), 1, f"collection errored: {exc}"
    return _parse_node_ids(proc.stdout), proc.returncode, _tail(proc)


def _suite_present(root: Path) -> bool:
    """Does the tree contain any test file at all? An empty result from a tree
    with no tests is fine (nothing to protect); an empty result from a tree
    WITH tests means collection is hiding or breaking them."""
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in ("venv", ".venv", "__pycache__", "node_modules")
        ]
        for name in filenames:
            if name.startswith("test_") and name.endswith(".py"):
                return True
            if name.endswith("_test.py"):
                return True
    return False


@dataclass
class InventoryResult:
    """One tree's collected test inventory.

    ``collected`` is every node ID pytest reports; ``servable`` is the subset
    that survives the skip-marker filter (i.e. would actually run). The
    difference (:attr:`skip_gated`) is the tests disabled behind
    ``@pytest.mark.skip``/``skipif`` — still collected, no longer an oracle.
    """

    collected: set[str] = field(default_factory=set)
    servable: set[str] = field(default_factory=set)
    collection_ok: bool = True
    collection_error: str | None = None

    @property
    def skip_gated(self) -> set[str]:
        return self.collected - self.servable


@dataclass(frozen=True)
class InventoryDiff:
    """Base vs candidate over the SERVABLE sets (skip-gated tests never counted
    as protected on either side). Lists are sorted so evidence is deterministic."""

    deleted: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    unchanged_count: int = 0

    @property
    def shrinks(self) -> bool:
        """True when any protected identity was lost — a deletion, a rename's
        old name, or a test newly disabled behind a skip marker."""
        return bool(self.deleted)


def collect_inventory(
    root: Path, pytest_args: list[str], *, timeout: int = _COLLECT_TIMEOUT
) -> InventoryResult:
    """Collect ``root``'s test inventory: two cheap passes, no test execution.

    Pass 1 is plain collection (every ID). Pass 2 re-collects with
    ``-m "not skip and not skipif"`` (the servable set); IDs that vanish under
    the filter are skip-gated. A nonzero exit from either pass, or zero
    collected IDs while the tree contains test files, is a collection failure
    (``collection_ok=False``) — the inventory is unverifiable, never assumed.
    """
    root = Path(root)
    all_ids, rc_all, err_all = _collect(root, pytest_args, (), timeout)
    servable, rc_serv, err_serv = _collect(root, pytest_args, _SKIP_FILTER, timeout)
    errors: list[str] = []
    for label, rc, err in (("full pass", rc_all, err_all), ("skip-filter pass", rc_serv, err_serv)):
        if rc == 5:
            # pytest's "no tests collected" exit — not an error in itself; a
            # tree with no test files has nothing to protect. Whether an empty
            # result hides a suite is judged by the suite-present rule below.
            continue
        if rc != 0:
            errors.append(f"{label} exit {rc}: {err}")
    if not all_ids and _suite_present(root):
        errors.append("no tests collected while the tree contains test files")
    return InventoryResult(
        collected=all_ids,
        servable=servable,
        collection_ok=not errors,
        collection_error="; ".join(errors) or None,
    )


def diff_inventory(base: InventoryResult, cand: InventoryResult) -> InventoryDiff:
    """Diff the protected (servable) sets. A rename is the old ID deleted plus
    the new one added; a newly skip-marked test is deleted from the servable
    set; un-skipping a previously gated test shows up as added (a genuine
    improvement, not a shrink)."""
    deleted = sorted(base.servable - cand.servable)
    added = sorted(cand.servable - base.servable)
    return InventoryDiff(
        deleted=deleted,
        added=added,
        unchanged_count=len(base.servable & cand.servable),
    )

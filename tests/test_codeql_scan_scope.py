"""`paths-ignore` must never take shipped code out of the CodeQL analysis.

An exclusion list is a quiet instrument: nothing fails when it removes too
much, the affected job just reports fewer alerts and still goes green. The
first version of this config carried `**/test_*.py`, which reads as "tests"
and in fact also matched `packages/maistro-rsi/src/maistro_rsi/test_inventory.py`
— runtime code that launches subprocesses against candidate repositories.

So the rule these tests pin is not "keep the list short", it is: an entry may
name a *location* that holds no shipped code, and may not name a filename
shape. A shape is what reaches across the tree into `packages/`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".github" / "codeql" / "codeql-config.yml"

#: Trees whose files are installed or served. `tests/` beneath them is not.
SHIPPED_TREES = (
    "packages/*/src",
    "packages/hive-conductor/backend",
    "packages/maistro-canvas/frontend/server",
)


def _ignore_patterns() -> list[str]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return list(config["paths-ignore"])


def _as_regex(pattern: str) -> re.Pattern[str]:
    """A CodeQL path glob as a regex over a repo-relative POSIX path.

    `**/` spans any number of directories (including none), `**` any text, `*`
    anything within one segment. Written out rather than borrowed from
    `fnmatch`, whose `*` crosses `/` and would make every pattern here look
    broader than it is.
    """
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:[^/]+/)*"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$")


def _shipped_sources() -> list[str]:
    seen: set[str] = set()
    for tree in SHIPPED_TREES:
        for base in REPO_ROOT.glob(tree):
            for path in base.rglob("*"):
                if path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
                    continue
                rel = path.relative_to(REPO_ROOT)
                parts = set(rel.parts)
                # Tests and vendored code are what the list is *for*; they are
                # not the shipped surface it must leave alone.
                if parts & {"tests", "node_modules", "dist", "third_party"}:
                    continue
                if ".test." in path.name:
                    continue
                seen.add(rel.as_posix())
    return sorted(seen)


def test_the_config_is_wired_into_the_workflow() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    assert "./.github/codeql/codeql-config.yml" in workflow


def test_no_shipped_source_file_is_excluded_from_analysis() -> None:
    patterns = [(p, _as_regex(p)) for p in _ignore_patterns()]
    sources = _shipped_sources()
    assert sources, "found no shipped sources — the tree layout changed, fix SHIPPED_TREES"

    excluded = sorted(
        f"{rel} (by {pattern})"
        for rel in sources
        for pattern, regex in patterns
        if regex.match(rel)
    )
    assert excluded == [], (
        "paths-ignore removes shipped code from the CodeQL scan:\n  " + "\n  ".join(excluded)
    )


def test_the_rsi_test_inventory_module_stays_in_scope() -> None:
    """The specific regression. It is named `test_inventory.py` and it is not a
    test: `candidate_fitness.py` and `local_loop.py` import it, and it runs a
    candidate repository's test suite in a subprocess."""
    rel = "packages/maistro-rsi/src/maistro_rsi/test_inventory.py"
    assert (REPO_ROOT / rel).is_file(), "module moved — update or drop this regression"

    for pattern in _ignore_patterns():
        assert not _as_regex(pattern).match(rel), f"{pattern} excludes shipped runtime code"


@pytest.mark.parametrize(
    "pattern",
    [
        "packages/maistro-core/tests/security/test_warden.py",
        "packages/hive-conductor/backend/tests/test_scheduler.py",
        "formal/models/test_warden_detector.py",
        "packages/maistro-canvas/frontend/server/security.test.js",
    ],
)
def test_real_test_files_are_still_excluded(pattern: str) -> None:
    """Narrowing the list must not have narrowed it into uselessness."""
    assert any(_as_regex(p).match(pattern) for p in _ignore_patterns())

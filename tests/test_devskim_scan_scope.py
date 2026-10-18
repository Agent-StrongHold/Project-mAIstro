"""DevSkim's `ignore-globs` must never take shipped code out of the scan.

An exclusion list is a quiet instrument: nothing fails when it removes too
much, the scan just reports less and still goes green. The CodeQL config
learned this the expensive way — `**/test_*.py` read as "tests" and also
matched `packages/maistro-rsi/src/maistro_rsi/test_inventory.py`, runtime code
that launches subprocesses against candidate repositories.

So the rule these tests pin is not "keep the list short", it is: a glob may
name a *location* that holds no shipped code, and may not name a filename
shape that reaches across the tree into `packages/`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "devskim.yml"

#: Trees whose files are installed, served, or rendered into a product.
SHIPPED_TREES = (
    "packages/*/src",
    "packages/hive-conductor/backend",
    "packages/hive-conductor/frontend/src",
    "packages/maistro-canvas/frontend/server",
    "packages/maistro-canvas/frontend/src",
    "templates",
    "scripts",
)

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".jinja", ".java", ".cs", ".go"}


def _ignore_globs() -> list[str]:
    """The globs the workflow actually passes to the action."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["lint"]["steps"]
    scanner = [s for s in steps if str(s.get("uses", "")).startswith("microsoft/DevSkim-Action")]
    assert len(scanner) == 1, "expected exactly one DevSkim scanner step"
    raw = scanner[0].get("with", {}).get("ignore-globs")
    assert raw, "the scanner step passes no ignore-globs — it would scan everything"
    return [glob.strip() for glob in raw.split(",") if glob.strip()]


def _as_regex(glob: str) -> re.Pattern[str]:
    """A DevSkim ignore glob as a regex over a repo-relative POSIX path.

    Written out rather than borrowed from `fnmatch`, whose `*` crosses `/` and
    would make every pattern here look broader than it is.
    """
    out = ""
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:[^/]+/)*"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(f"^{out}$")


def _shipped_sources() -> list[str]:
    seen: set[str] = set()
    for tree in SHIPPED_TREES:
        for base in REPO_ROOT.glob(tree):
            for path in base.rglob("*"):
                if path.suffix not in SOURCE_SUFFIXES:
                    continue
                rel = path.relative_to(REPO_ROOT)
                parts = set(rel.parts)
                # Tests and vendored code are what the list is *for*; they are
                # not the shipped surface it must leave alone.
                if parts & {"tests", "__tests__", "node_modules", "dist", "third_party"}:
                    continue
                if ".test." in path.name:
                    continue
                seen.add(rel.as_posix())
    return sorted(seen)


def test_the_scanner_step_is_configured() -> None:
    assert _ignore_globs(), "DevSkim must not run unconfigured"


def test_the_actions_own_defaults_are_not_silently_dropped() -> None:
    """Passing `ignore-globs` REPLACES the action default rather than adding to
    it, so anything the default covered has to be restated here."""
    globs = _ignore_globs()
    for inherited in ("**/.git/**", "**/bin/**"):
        assert inherited in globs, f"{inherited} was the action default and is now unset"


def test_no_glob_names_a_filename_shape_reaching_into_packages() -> None:
    """`**/test_*.py` is the shape that broke the CodeQL config. A glob whose
    last segment is a wildcard over a *name* can match anywhere, including
    shipped trees; one that ends in a directory segment cannot."""
    offenders = [
        glob
        for glob in _ignore_globs()
        if not glob.endswith("/**") and not glob.startswith("**/*.test.")
    ]
    assert offenders == [], f"globs matching by filename shape: {offenders}"


def test_no_shipped_source_file_is_excluded_from_the_scan() -> None:
    globs = [(g, _as_regex(g)) for g in _ignore_globs()]
    sources = _shipped_sources()
    assert sources, "found no shipped sources — the tree layout changed, fix SHIPPED_TREES"

    excluded = sorted(
        f"{rel} (by {glob})" for rel in sources for glob, rx in globs if rx.match(rel)
    )
    assert excluded == [], (
        "ignore-globs removes shipped code from the DevSkim scan:\n  " + "\n  ".join(excluded)
    )


def test_the_rsi_test_inventory_module_stays_in_scope() -> None:
    """The regression that motivated this guard, kept by name. It is called
    `test_inventory.py` and it is not a test: `candidate_fitness.py` and
    `local_loop.py` import it, and it runs a candidate repository's suite in a
    subprocess."""
    rel = "packages/maistro-rsi/src/maistro_rsi/test_inventory.py"
    assert (REPO_ROOT / rel).is_file(), "module moved — update or drop this regression"
    for glob in _ignore_globs():
        assert not _as_regex(glob).match(rel), f"{glob} excludes shipped runtime code"


def test_a_shipped_template_under_a_docs_directory_stays_in_scope() -> None:
    """`**/docs/**` reads as documentation and also reaches
    `templates/*/docs/**.jinja`, which is rendered into generated products."""
    rel = "templates/autonoetic/docs/adr/ADR-001-generated-product-baseline.md.jinja"
    if not (REPO_ROOT / rel).is_file():
        pytest.skip("template moved; the invariant is covered by the sweep above")
    for glob in _ignore_globs():
        assert not _as_regex(glob).match(rel), f"{glob} excludes a shipped template"


@pytest.mark.parametrize(
    "path",
    [
        "packages/maistro-core/tests/security/test_warden.py",
        "packages/hive-conductor/backend/tests/test_scheduler.py",
        "packages/maistro-canvas/frontend/server/security.test.js",
        "packages/maistro-evolve/src/maistro_evolve/benchmarks/third_party/ifeval/instructions.py",
    ],
)
def test_the_noisy_trees_are_still_excluded(path: str) -> None:
    """Narrowing must not have narrowed the list into uselessness."""
    assert any(_as_regex(g).match(path) for g in _ignore_globs())

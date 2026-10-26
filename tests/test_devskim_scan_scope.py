"""DevSkim must scan shipped code and skip non-product noise.

An exclusion list is a quiet instrument: nothing fails when it removes too
much, the scan just reports less and still goes green. The CodeQL config
learned this the expensive way — `**/test_*.py` read as "tests" and also
matched `packages/maistro-rsi/src/maistro_rsi/test_inventory.py`, runtime code
that launches subprocesses against candidate repositories.

So the rule these tests pin is not "keep the list short", it is: a glob may
name a *location* that holds no shipped code, and may not name a filename
shape that reaches across the tree into `packages/`. Non-product roots
(`.github/`, `deploy/`, …) are kept out by `--include-globs` allowlisting the
shipped trees, not by a broad `**/deploy/**` deny that would also hide
`templates/**/deploy/**`.
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


def _scanner_step() -> dict[str, object]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["lint"]["steps"]
    scanner = [s for s in steps if str(s.get("uses", "")).startswith("microsoft/DevSkim-Action")]
    assert len(scanner) == 1, "expected exactly one DevSkim scanner step"
    return scanner[0]


def _ignore_globs() -> list[str]:
    """The globs the workflow actually passes to the action."""
    raw = _scanner_step().get("with", {}).get("ignore-globs")  # type: ignore[union-attr]
    assert raw, "the scanner step passes no ignore-globs — it would scan everything"
    return [glob.strip() for glob in str(raw).split(",") if glob.strip()]


def _include_globs() -> list[str]:
    """Allowlist passed via ``extra-options: --include-globs …``."""
    extra = str(_scanner_step().get("with", {}).get("extra-options") or "")  # type: ignore[union-attr]
    match = re.search(r"--include-globs\s+(\S+)", extra)
    assert match, "DevSkim must pass --include-globs so non-product roots are never scanned"
    return [glob.strip() for glob in match.group(1).split(",") if glob.strip()]


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


def _is_scanned(path: str) -> bool:
    """Whether DevSkim would analyze ``path`` under the configured allow/deny."""
    allowed = any(_as_regex(g).match(path) for g in _include_globs())
    denied = any(_as_regex(g).match(path) for g in _ignore_globs())
    return allowed and not denied


def _shipped_sources() -> list[str]:
    seen: set[str] = set()
    for tree in SHIPPED_TREES:
        for base in REPO_ROOT.glob(tree):
            for path in base.rglob("*"):
                if path.suffix not in SOURCE_SUFFIXES:
                    continue
                rel = path.relative_to(REPO_ROOT)
                parts = set(rel.parts)
                # Tests, vendored code, and the vendored swagger-ui-dist
                # release (#1425, served by backend/routes/api_docs.py with
                # sha256 provenance pinned in `_ASSETS` and enforced by
                # `backend/tests/test_docs_first_party.py`) are what the list
                # is *for*; they are not the shipped surface it must leave
                # alone.
                if parts & {
                    "tests",
                    "__tests__",
                    "node_modules",
                    "dist",
                    "third_party",
                    "swagger-ui",
                    "corpora",
                    "eval",
                }:
                    continue
                # Bundled Open Design fixtures (json/md/css only) under
                # systems/catalog — excluded as a location, not a filename shape.
                if "systems" in rel.parts and "catalog" in rel.parts:
                    try:
                        systems_i = rel.parts.index("systems")
                    except ValueError:
                        systems_i = -1
                    if (
                        systems_i >= 0
                        and systems_i + 1 < len(rel.parts)
                        and rel.parts[systems_i + 1] == "catalog"
                    ):
                        continue
                if ".test." in path.name:
                    continue
                seen.add(rel.as_posix())
    return sorted(seen)


def test_the_scanner_step_is_configured() -> None:
    assert _ignore_globs(), "DevSkim must not run unconfigured"
    assert _include_globs(), "DevSkim must allowlist shipped trees"


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


def test_directory_globs_are_absolute_path_safe() -> None:
    """DevSkim DenyFilters match absolute paths under $GITHUB_WORKSPACE.

    A glob like `.github/**` or `deploy/**` only matches when the path *starts*
    with that prefix, so it never hits
    `/home/runner/work/.../.github/workflows/ci.yml`. Every directory ignore
    must therefore start with `**/` (the form that matched `**/tests/**` and
    friends all along).
    """
    offenders = [g for g in _ignore_globs() if g.endswith("/**") and not g.startswith("**/")]
    assert offenders == [], (
        "directory ignore-globs must start with **/ so they match absolute "
        "runner paths:\n  " + "\n  ".join(offenders)
    )


def test_no_shipped_source_file_is_excluded_from_the_scan() -> None:
    sources = _shipped_sources()
    assert sources, "found no shipped sources — the tree layout changed, fix SHIPPED_TREES"

    excluded = sorted(rel for rel in sources if not _is_scanned(rel))
    assert excluded == [], (
        "include/ignore configuration removes shipped code from the DevSkim scan:\n  "
        + "\n  ".join(excluded)
    )


def test_the_rsi_test_inventory_module_stays_in_scope() -> None:
    """The regression that motivated this guard, kept by name. It is called
    `test_inventory.py` and it is not a test: `candidate_fitness.py` and
    `local_loop.py` import it, and it runs a candidate repository's suite in a
    subprocess."""
    rel = "packages/maistro-rsi/src/maistro_rsi/test_inventory.py"
    assert (REPO_ROOT / rel).is_file(), "module moved — update or drop this regression"
    assert _is_scanned(rel), "shipped runtime code dropped from the DevSkim scan"


def test_a_shipped_template_under_a_docs_directory_stays_in_scope() -> None:
    """`**/docs/**` reads as documentation and also reaches
    `templates/*/docs/**.jinja`, which is rendered into generated products."""
    rel = "templates/autonoetic/docs/adr/ADR-001-generated-product-baseline.md.jinja"
    if not (REPO_ROOT / rel).is_file():
        pytest.skip("template moved; the invariant is covered by the sweep above")
    assert _is_scanned(rel), "shipped template dropped from the DevSkim scan"


def test_shipped_template_deploy_stays_in_scope() -> None:
    """A broad ``**/deploy/**`` deny would hide product compose templates."""
    rel = "templates/autonoetic/deploy/compose.yml.jinja"
    if not (REPO_ROOT / rel).is_file():
        pytest.skip("template moved; the invariant is covered by the sweep above")
    assert _is_scanned(rel), "**/deploy/** must not exclude shipped templates"


@pytest.mark.parametrize(
    "path",
    [
        "packages/maistro-core/tests/security/test_warden.py",
        "packages/hive-conductor/backend/tests/test_scheduler.py",
        "packages/maistro-canvas/frontend/server/security.test.js",
        "packages/maistro-evolve/src/maistro_evolve/benchmarks/third_party/ifeval/instructions.py",
        "packages/hive-conductor/backend/static/swagger-ui/swagger-ui-bundle.js",
        "packages/maistro-design/src/maistro_design/systems/catalog/catalog.json",
        "packages/maistro-evolve/src/maistro_evolve/benchmarks/corpora/repo_history_tasks.json",
        "formal/models/test_pipeline_integration.py",
        ".github/workflows/ci.yml",
        "deploy/scripts/backup.sh",
        "alembic/env.py",
        "packages/hive-conductor/eval/departments/engineering.py",
        "quality/vulture-baseline.json",
    ],
)
def test_the_noisy_trees_are_still_excluded(path: str) -> None:
    """Non-product roots miss the allowlist; nested noise hits ignore-globs."""
    assert not _is_scanned(path), f"{path} is still in the DevSkim scan"

#!/usr/bin/env python3
"""Single-source version bump across the monorepo (E1, issue #294).

The monorepo versions in lockstep: one `VERSION` file at the repo root is the
source of truth, and every other version site — each package's
`pyproject.toml`, each package's `__version__` fallback (when
`importlib.metadata` can't find installed dist-info, e.g. an editable/unbuilt
checkout), the inter-package dependency lower bounds, and a handful of
app-level `FastAPI(version=...)` literals in the non-packaged apps
(hive-conductor, the turing backend, the canvas frontend's lulu service) —
must agree with it.

Usage:
    scripts/bump_version.py 1.0.0     # rewrite every site to 1.0.0 + VERSION
    scripts/bump_version.py --check   # verify every site agrees with VERSION

`--check` is meant to run in CI (quality.yml) so drift is caught before merge,
not just at bump time.

Deliberately NOT covered here (out of E1 scope):
- Upper-bounding the inter-package dependency constraints to `<2` — that's
  E2 (#295), which also adds the `[tool.uv.workspace]` table.
- Running `uv lock` — the lockfile pins these same package versions
  (`uv.lock`'s `editable = "packages/..."` entries) and goes stale after a
  bump; re-run `uv lock` by hand (or via CI) after bumping.
- Per-generated-skill/agent-spec version fields (e.g.
  `packages/hive-conductor/backend/routes/skills.py`'s `forge_skill()`
  default, `packages/maistro-canvas/agents/davinci/agent.yaml`'s
  `spec_version`) — those are object/schema versions, not the package or
  app version.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"

_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
_PYPROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
# Matches both the `__version__` fallback every package's __init__.py carries
# and maistro-server/main.py's pre-existing `APP_VERSION` fallback (the two
# names that already existed before this script — see the module docstring).
_VERSION_FALLBACK_RE = re.compile(r'(?:__version__|APP_VERSION) = "([^"]+)-dev"')
_DICT_VERSION_RE = re.compile(r'"version": "([^"]+)"')
_KWARG_VERSION_RE = re.compile(r'version="([^"]+)"')


@dataclass(frozen=True)
class Site:
    """One version occurrence: a file + a regex whose sole capture group is
    the version substring to read or overwrite."""

    path: Path
    pattern: re.Pattern[str]
    label: str

    def extract(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        matches = self.pattern.findall(text)
        if len(matches) != 1:
            raise SystemExit(
                f"{self.label}: expected exactly 1 match in {self.path}, found {len(matches)}"
            )
        return matches[0]

    def rewrite(self, new_version: str) -> None:
        text = self.path.read_text(encoding="utf-8")
        new_text, count = self.pattern.subn(
            lambda m: m.group(0).replace(m.group(1), new_version), text
        )
        if count != 1:
            raise SystemExit(
                f"{self.label}: expected exactly 1 match in {self.path}, found {count}"
            )
        self.path.write_text(new_text, encoding="utf-8")


def _pyproject(rel_path: str) -> Site:
    return Site(ROOT / rel_path, _PYPROJECT_VERSION_RE, f"pyproject:{rel_path}")


def _version_fallback(rel_path: str) -> Site:
    return Site(ROOT / rel_path, _VERSION_FALLBACK_RE, f"version fallback:{rel_path}")


def _interpkg_dep(rel_path: str, pkg_expr: str) -> Site:
    pattern = re.compile(rf'"{re.escape(pkg_expr)}>=([\d.]+)"')
    return Site(ROOT / rel_path, pattern, f"inter-package dep:{rel_path}:{pkg_expr}")


def _app_literal(rel_path: str, pattern: re.Pattern[str]) -> Site:
    return Site(ROOT / rel_path, pattern, f"app version literal:{rel_path}")


# Every [project] `version = "..."` line — root workspace meta-package + all
# 9 library packages. hive-conductor has no pyproject.toml (see its CLAUDE.md
# — an application, not a library) and is intentionally absent here.
_PYPROJECT_SITES = [
    _pyproject("pyproject.toml"),
    _pyproject("packages/maistro-core/pyproject.toml"),
    _pyproject("packages/maistro-canvas/pyproject.toml"),
    _pyproject("packages/maistro-server/pyproject.toml"),
    _pyproject("packages/maistro-turing/pyproject.toml"),
    _pyproject("packages/maistro-evolve/pyproject.toml"),
    _pyproject("packages/maistro-registry/pyproject.toml"),
    _pyproject("packages/maistro-rsi/pyproject.toml"),
    _pyproject("packages/maistro-design/pyproject.toml"),
    _pyproject("packages/maistro-bootstrap/pyproject.toml"),
]

# Every package's `__version__`/`APP_VERSION` PackageNotFoundError fallback
# string — the value returned when importlib.metadata can't find installed
# dist-info (e.g. running straight off PYTHONPATH in dev, the exact scenario
# the two health-endpoint tests exercise).
_VERSION_FALLBACK_SITES = [
    _version_fallback("packages/maistro-core/src/maistro/__init__.py"),
    _version_fallback("packages/maistro-canvas/src/maistro_canvas/__init__.py"),
    _version_fallback("packages/maistro-server/src/maistro_server/__init__.py"),
    # main.py's pre-existing APP_VERSION fallback (used by /health's response
    # and by both test_health.py's APP_VERSION-based assertions) — distinct
    # from __init__.py's __version__ above, same fallback pattern.
    _version_fallback("packages/maistro-server/src/maistro_server/main.py"),
    _version_fallback("packages/maistro-turing/src/maistro_turing/__init__.py"),
    _version_fallback("packages/maistro-evolve/src/maistro_evolve/__init__.py"),
    _version_fallback("packages/maistro-rsi/src/maistro_rsi/__init__.py"),
    _version_fallback("packages/maistro-design/src/maistro_design/__init__.py"),
    _version_fallback("packages/maistro-bootstrap/src/maistro_bootstrap/__init__.py"),
    _version_fallback("packages/maistro-registry/src/maistro_registry/__init__.py"),
]

# Inter-package dependency LOWER bounds only — adding the `<2` upper bound is
# E2 (#295) scope, not this script's.
_INTERPKG_SITES = [
    _interpkg_dep("packages/maistro-canvas/pyproject.toml", "maistro-core"),
    # `[llm]`, not bare: maistro-server reaches FastMCP through the core tool
    # modules it imports and now asks for the extra rather than restating the
    # pin (#514). The site has to name the expression the file actually holds
    # or the version bound stops being checked -- silently, since "found 0"
    # was only a failure because this list said one was expected.
    _interpkg_dep("packages/maistro-server/pyproject.toml", "maistro-core[llm]"),
    _interpkg_dep("packages/maistro-turing/pyproject.toml", "maistro-core"),
    _interpkg_dep("packages/maistro-rsi/pyproject.toml", "maistro-core[llm]"),
    _interpkg_dep("packages/maistro-rsi/pyproject.toml", "maistro-evolve"),
    _interpkg_dep("packages/maistro-rsi/pyproject.toml", "maistro-bootstrap"),
    _interpkg_dep("packages/maistro-design/pyproject.toml", "maistro-core"),
    _interpkg_dep("packages/maistro-design/pyproject.toml", "maistro-canvas"),
]

# App-level FastAPI(version=...) / dict "version" literals in the
# non-packaged apps (no pyproject.toml / installed dist-info to source from).
_APP_LITERAL_SITES = [
    _app_literal("packages/hive-conductor/backend/routes/health.py", _DICT_VERSION_RE),
    _app_literal("packages/hive-conductor/backend/main.py", _KWARG_VERSION_RE),
    _app_literal("packages/maistro-turing/backend/main.py", _KWARG_VERSION_RE),
    _app_literal("packages/maistro-canvas/frontend/server/lulu/service.py", _KWARG_VERSION_RE),
]

ALL_SITES = _PYPROJECT_SITES + _VERSION_FALLBACK_SITES + _INTERPKG_SITES + _APP_LITERAL_SITES


def check() -> int:
    if not VERSION_FILE.exists():
        print(f"::error::{VERSION_FILE} does not exist", file=sys.stderr)
        return 1
    expected = VERSION_FILE.read_text(encoding="utf-8").strip()
    mismatches: list[str] = []
    for site in ALL_SITES:
        try:
            actual = site.extract()
        except SystemExit as exc:
            mismatches.append(str(exc))
            continue
        if actual != expected:
            mismatches.append(f"{site.label}: found {actual!r}, expected {expected!r}")
    if mismatches:
        print(
            f"::error::version consistency check FAILED against VERSION={expected!r} "
            f"({len(mismatches)} of {len(ALL_SITES)} sites disagree):",
            file=sys.stderr,
        )
        for mismatch in mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        return 1
    print(f"version consistency check passed: {len(ALL_SITES)} sites agree on {expected!r}")
    return 0


def bump(new_version: str) -> int:
    if not _SEMVER_RE.fullmatch(new_version):
        print(
            f"::error::version must be a bare semver core X.Y.Z (no 'v' prefix, no "
            f"pre-release suffix — rc suffixes live only on the git tag, see E3/#296), "
            f"got {new_version!r}",
            file=sys.stderr,
        )
        return 1
    for site in ALL_SITES:
        site.rewrite(new_version)
    VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")
    print(f"bumped {len(ALL_SITES)} sites + {VERSION_FILE} to {new_version}")
    print("Next: run `uv lock` to refresh uv.lock, then `scripts/bump_version.py --check`.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("version", nargs="?", help="new version, e.g. 1.0.0")
    parser.add_argument(
        "--check", action="store_true", help="verify every site agrees with VERSION; write nothing"
    )
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.version:
        return bump(args.version)
    parser.error("either a version positional argument or --check is required")
    return 2  # unreachable — parser.error() raises SystemExit


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

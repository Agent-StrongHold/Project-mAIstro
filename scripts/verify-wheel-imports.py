#!/usr/bin/env python3
"""Verify every built wheel imports from a clean venv.

Why this exists
---------------
`maistro.identity` shipped an unguarded top-level `import nacl` / `import bip_utils`
while neither library was declared by `maistro-core`. Nothing caught it: the repo's
own test and lint jobs run inside a root `uv sync` environment where a *dev extra*
happened to supply both. Every CI job was green while `pip install maistro-core`
raised ImportError for a documented subsystem.

This script closes that loop. It installs the built wheels into throwaway venvs and
imports them, so the thing CI checks is the thing a downstream consumer gets.

Two tiers, deliberately:

  bare  Install the wheel with **no extras** and import the documented public
        surface. This is the contract downstream products consume, and it is the
        tier that would have caught the identity bug the day it landed.

  all   Install the widest extra and walk **every** module recursively, with zero
        tolerated failures. No allowlist file: an allowlist is where failures get
        quietly parked, so a module that cannot be imported is a bug to fix or a
        dependency to declare, not a line to add here.

Usage
-----
    python scripts/verify-wheel-imports.py --dist dist/            # both tiers
    python scripts/verify-wheel-imports.py --dist dist/ --mode bare
    python scripts/verify-wheel-imports.py --dist dist/ --only maistro-core
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# The documented public surface of maistro-core, mirroring the subsystem table in
# the repo-root CLAUDE.md plus the root-level modules. Keep these in sync: an
# import that is documented as importable and is not listed here is untested.
CORE_PUBLIC_SURFACE = [
    "maistro",
    "maistro.a2a",
    "maistro.agents",
    "maistro.agents.intents",
    # The S3-compatible archive tier (ADR-082226-f436). Importable from a bare
    # install: the module resolves and raises a clear error when the `s3` extra
    # is absent, rather than failing at import.
    "maistro.archive",
    "maistro.auth",
    "maistro.builders",
    "maistro.capabilities",
    "maistro.classifier",
    "maistro.conduit",
    "maistro.container",
    "maistro.credentials",
    "maistro.events",
    "maistro.graph",
    "maistro.http",
    "maistro.memory",
    "maistro.ontology",
    "maistro.orchestrator",
    "maistro.persistence",
    "maistro.projects",
    "maistro.prompts",
    "maistro.protocols",
    "maistro.quota",
    "maistro.resilience",
    "maistro.router",
    "maistro.runs",
    "maistro.runtime",
    "maistro.scheduling",
    "maistro.security",
    "maistro.sessions",
    "maistro.skills",
    "maistro.testing",
    "maistro.types",
    "maistro.workspaces",
    # Root-level modules (reactor loop, secrets vault, privilege split, state).
    "maistro.privilege",
    "maistro.reactor",
    "maistro.state",
    "maistro.vault",
    # Added 2026-07: these were importable from a bare install all along but
    # were simply never listed, so the enumeration gate reported each as a gap
    # ("importable module absent from CORE_PUBLIC_SURFACE") and all 18 sat in
    # the tolerated baseline. Listing them turns the bare tier into an actual
    # assertion about them rather than tolerated silence. They are NOT
    # extras-gated — that carve-out is SURFACE_EXEMPT (maistro.cli,
    # maistro.identity), and anything here that needs an extra belongs there
    # with a written reason instead.
    "maistro.code_registry",
    "maistro.codebase",
    "maistro.collaboration",
    "maistro.config",
    "maistro.constants",
    "maistro.delivery",
    "maistro.governance",
    "maistro.integrations",
    "maistro.observability",
    "maistro.personas",
    "maistro.policy",
    "maistro.portability",
    "maistro.providers",
    "maistro.repertoire",
    "maistro.sandbox",
    "maistro.tasks",
    "maistro.tools",
]


@dataclass(frozen=True)
class Package:
    """A distribution to build, install and import."""

    dist: str
    """PyPI-style distribution name, e.g. maistro-core."""

    root: str
    """Top-level import package, e.g. maistro."""

    surface: list[str] = field(default_factory=list)
    """Modules to import in `bare` mode. Defaults to [root] when empty."""

    widest_extra: str | None = None
    """Extra installed in `all` mode, e.g. "all". None means install plain."""

    data_files: list[str] = field(default_factory=list)
    """Non-Python files that must ship inside the wheel, relative to `root`.

    Every check above this one is about code, and a packaging change that drops
    the data leaves the code importing perfectly. maistro-design's bundled
    design systems are six directories of JSON, CSS and Markdown; without them
    `load_bundled` raises FileNotFoundError at container startup and nothing in
    CI has an opinion (#293).
    """

    def bare_surface(self) -> list[str]:
        return self.surface or [self.root]


# Two maistro-core subpackages are intentionally absent from the bare surface
# above, because they are gated behind extras. Both are still swept in `all` mode,
# so neither is exempt from the gate — only from the no-extras tier:
#   maistro.cli       typer/rich  -> `tui` extra
#   maistro.identity  bip-utils   -> `identity` extra (coincurve has no wheel for
#                                    the Python the API image ships)
#: The four files `maistro_design.systems.importer` reads for one system.
#: Mirrors `importer.ESSENTIAL_FILES`; kept here rather than imported because
#: this script must run before anything is installed.
ESSENTIAL_FILES = ("manifest.json", "DESIGN.md", "tokens.css", "design-tokens.json")

PACKAGES = [
    Package("maistro-core", "maistro", CORE_PUBLIC_SURFACE, widest_extra="all"),
    Package("maistro-canvas", "maistro_canvas", widest_extra="export"),
    Package("maistro-server", "maistro_server"),
    Package("maistro-turing", "maistro_turing"),
    Package(
        "maistro-design",
        "maistro_design",
        # One file per bundled system rather than the directory, because a
        # partial copy is the failure a directory check would pass. `default`
        # is the slug `DiscoveryResult` falls back to, so its absence is the
        # one that reaches every caller.
        #
        # `design-tokens.json` is in this list precisely because
        # `_read_system_files()` treats it as OPTIONAL (#413). Drop it in
        # packaging and nothing complains: the wheel imports, `load_bundled`
        # succeeds, startup reports ready -- and every system loads with zero
        # colour and spacing tokens, which is the empty shell #293 removed,
        # reached from the other direction. The one file whose absence is
        # silent is the one that most needs declaring.
        data_files=[
            f"systems/bundled/{slug}/{name}"
            for slug in ("default", "shadcn", "apple", "material", "editorial", "enterprise")
            for name in ("manifest.json", "DESIGN.md", "tokens.css", "design-tokens.json")
        ]
        # The catalogue index AND a payload from it. The index alone would let
        # a wheel advertise 144 importable systems whose files are absent --
        # `import_from_catalog` reads `systems/catalog/<slug>/`, not the index.
        + [
            "systems/catalog/catalog.json",
            *(f"systems/catalog/airbnb/{name}" for name in ESSENTIAL_FILES),
        ],
    ),
    # [ifeval] carries the vendored Google IFEval verifier's own runtime deps
    # (nltk, langdetect, absl-py, immutabledict). That vendored tree imports
    # them at module scope, and this check walks *every* module, so the bare
    # wheel cannot import it. Declaring the widest extra is the mechanism for
    # exactly this — same as maistro-canvas[export] and
    # maistro-bootstrap[builders] above — not an exclusion.
    Package("maistro-evolve", "maistro_evolve", widest_extra="ifeval"),
    Package("maistro-registry", "maistro_registry"),
    Package("maistro-rsi", "maistro_rsi"),
    Package("maistro-bootstrap", "maistro_bootstrap", widest_extra="builders"),
]

# Distributions that are BUILT by the CI loop but not import-verified here. Both
# entries state a structural reason, not a convenience: a skip printed by
# _announce_exclusions is a visible reduction in coverage, and the day the reason
# stops being true the entry must go.
SKIPPED_DISTS = {
    "maistro-workspace": "dependency-only meta package, builds an empty wheel by design",
    "hive-conductor": (
        "flat module layout: packages/hive-conductor/backend/ has no package root "
        "(no backend/__init__.py) and the app imports its own modules "
        "top-level-relative — `from config import get_settings`, `from routes "
        "import ...`, `from middleware.auth import AuthMiddleware` — which only "
        "resolve with backend/ itself on sys.path (the Dockerfile sets "
        "PYTHONPATH=/app/backend; backend/tests/conftest.py inserts it at "
        "sys.path[0]). The wheel therefore ships those sources remapped under a "
        "hive_conductor/ prefix, and `import hive_conductor.main` raises "
        "ModuleNotFoundError: config. Lifting this skip means giving backend/ a "
        "real package root and rewriting every intra-app import to be "
        "package-relative, then updating the Dockerfile PYTHONPATH and the "
        "conftest sys.path shim to match — a refactor, not a packaging change. "
        "It is an application, not a published library (not in the PyPI set), so "
        "the build itself is the coverage that matters here"
    ),
}

# Probe executed inside the clean venv. Prints one JSON object so the parent can
# report every failure at once instead of stopping at the first.
PROBE = r"""
import importlib, json, pathlib, pkgutil, sys, traceback

mode, root, surface = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
data_files = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []
failures, checked = [], []


def attempt(name):
    checked.append(name)
    try:
        return importlib.import_module(name)
    except BaseException as exc:            # noqa: BLE001 - report, never mask
        failures.append({
            "module": name,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=6),
        })
        return None


if mode == "bare":
    for name in surface:
        attempt(name)
else:
    pkg = attempt(root)
    if pkg is not None and hasattr(pkg, "__path__"):
        names = sorted(i.name for i in pkgutil.walk_packages(pkg.__path__, prefix=root + "."))
        for name in names:
            attempt(name)

# Data files, resolved against the INSTALLED package rather than the source
# tree -- the whole point is that the wheel carries them.
if data_files:
    installed = sys.modules.get(root) or attempt(root)
    base = pathlib.Path(installed.__file__).parent if installed is not None else None
    for rel in data_files:
        checked.append(rel)
        if base is None or not (base / rel).is_file():
            failures.append({
                "module": f"{root}/{rel}",
                "error": "packaged data file missing from the wheel",
                "traceback": "",
            })

print(json.dumps({"checked": len(checked), "failures": failures}))
"""


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, **kw)  # type: ignore[call-overload,no-any-return]


def find_wheel(dist_dir: Path, dist: str) -> Path | None:
    """Locate the built wheel for a distribution (underscored file name)."""
    matches = sorted(dist_dir.glob(f"{dist.replace('-', '_')}-*.whl"))
    return matches[-1] if matches else None


def requires_python_minor(wheel: Path) -> int | None:
    """Minimum 3.x minor version from the wheel's Requires-Python, if declared.

    Deliberately handles only the `>=3.N` form, which is all this repo uses, so the
    script needs no third-party version parser to run on a bare interpreter.
    """
    with zipfile.ZipFile(wheel) as zf:
        meta = next((n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None)
        if meta is None:
            return None
        for line in zf.read(meta).decode("utf-8", "replace").splitlines():
            if line.startswith("Requires-Python:"):
                m = re.search(r">=\s*3\.(\d+)", line)
                return int(m.group(1)) if m else None
            if not line.strip():
                break
    return None


def check(pkg: Package, mode: str, dist_dir: Path, uv: str, py: str) -> tuple[bool | None, str]:
    """Install pkg's wheel into a fresh venv and import it.

    Returns (True, detail) on success, (False, detail) on failure, or (None, reason)
    when the package cannot run on the target interpreter at all.
    """
    wheel = find_wheel(dist_dir, pkg.dist)
    if wheel is None:
        return False, f"no wheel found in {dist_dir} — did the build step run?"

    needs = requires_python_minor(wheel)
    target = int(py.split(".")[1])
    if needs is not None and target < needs:
        return None, f"needs Python >=3.{needs}, target is {py}"

    spec = str(wheel.resolve())
    if mode == "all" and pkg.widest_extra:
        # PEP 508 direct reference, so extras apply to a local wheel path.
        spec = f"{pkg.dist}[{pkg.widest_extra}] @ {wheel.resolve().as_uri()}"

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        venv = tmpdir / ".venv"

        # Scrub the inherited environment: the repo sets PYTHONPATH to packages/*/src
        # in several CI jobs, and any leak would let source satisfy an import the
        # wheel cannot -- exactly the blind spot this job exists to remove.
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}}
        env["UV_NO_CONFIG"] = "1"

        made = _run([uv, "venv", "--python", py, str(venv)], cwd=tmpdir, env=env)
        if made.returncode != 0:
            return False, f"uv venv failed:\n{made.stderr.strip()}"

        # --find-links resolves sibling maistro-* deps from the same dist/ dir;
        # these packages are not published, so PyPI cannot satisfy them.
        install = _run(
            [uv, "pip", "install", "--python", str(venv), "--find-links", str(dist_dir), spec],
            cwd=tmpdir,
            env=env,
        )
        if install.returncode != 0:
            return False, f"install failed:\n{install.stderr.strip()[-2000:]}"

        python = venv / "bin" / "python"
        if not python.exists():  # Windows layout
            python = venv / "Scripts" / "python.exe"

        # Keep the repo off sys.path[0] — without it `packages/*/src` or a stray
        # `maistro/` in the working tree could satisfy the import and this check
        # would pass without having exercised the wheel.
        #
        # The cwd must also NOT be an ancestor of the venv. nltk ships an import
        # hook (nltk/inisec.py) that refuses any nltk-initiated import whose
        # origin resolves inside the cwd; with the venv at `tmpdir/.venv` and
        # cwd=tmpdir, the entire site-packages tree is "inside the cwd", so
        # nltk blocked its own transitive `regex` import. An empty sibling
        # directory satisfies both constraints.
        probe_cwd = tmpdir / "probe-cwd"
        probe_cwd.mkdir(exist_ok=True)
        probe = _run(
            [
                str(python),
                "-c",
                PROBE,
                mode,
                pkg.root,
                json.dumps(pkg.bare_surface()),
                json.dumps(pkg.data_files),
            ],
            cwd=probe_cwd,
            env=env,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            return False, f"probe crashed:\n{probe.stdout.strip()}\n{probe.stderr.strip()[-2000:]}"

        return render(json.loads(probe.stdout.strip().splitlines()[-1]))


def render(result: dict) -> tuple[bool, str]:
    """Turn one probe payload into the (ok, detail) pair `check()` returns.

    Split out from `check()` because everything above it needs a built wheel and
    a clean venv, and this does not -- so the wording a reader acts on is
    testable without a five-minute build.

    "check(s)", not "module(s) failed to import": the list now also carries
    packaged data files, which do not import (#293).
    """
    failures = result["failures"]
    if not failures:
        return True, f"{result['checked']} check(s) passed"
    lines = [f"{len(failures)} of {result['checked']} check(s) failed:"]
    for f in failures:
        lines.append(f"  {f['module']}: {f['error']}")
        if f.get("traceback", "").strip():
            lines.append("    " + f["traceback"].strip().replace("\n", "\n    "))
    return False, "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dist", type=Path, default=Path("dist"), help="directory of built wheels")
    ap.add_argument("--mode", choices=["bare", "all", "both"], default="both")
    ap.add_argument("--only", action="append", default=[], help="limit to these dist names")
    ap.add_argument(
        "--python",
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
        help="interpreter version for the throwaway venvs (default: the running one)",
    )
    return ap.parse_args()


def _announce_exclusions(packages: list[Package]) -> None:
    """State exclusions out loud: a gate whose coverage silently shrinks reads the
    same as one that passes."""
    for dist, why in sorted(SKIPPED_DISTS.items()):
        print(f"skip  {dist}: {why}")
    excluded = {p.dist for p in PACKAGES} - {p.dist for p in packages}
    if excluded:
        print(f"skip  {sorted(excluded)}: excluded by --only")


def _report(failed: list[str], skipped: list[str], py: str) -> int:
    print()
    if skipped:
        # Never let reduced coverage read as a pass.
        print(f"{len(skipped)} check(s) skipped on Python {py}:")
        for s in skipped:
            print(f"  {s}")
        print("Run with --python matching those packages to cover them.\n")
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        print(
            "\nA failure here means a wheel does not import as published. Fix by declaring the\n"
            "missing dependency on the package that imports it -- not by adding it to a dev\n"
            "extra, and not by adding an exclusion to this script."
        )
        return 1
    print(f"All wheels import from a clean venv (Python {py}).")
    return 0


def main() -> int:
    args = _parse_args()

    uv = shutil.which("uv")
    if uv is None:
        print("error: uv not on PATH", file=sys.stderr)
        return 2
    if not args.dist.is_dir():
        print(f"error: {args.dist} is not a directory", file=sys.stderr)
        return 2
    # Absolute: every install and probe runs with cwd set to a scratch dir, so a
    # relative --dist would resolve against the wrong directory.
    dist_dir = args.dist.resolve()

    packages = [p for p in PACKAGES if not args.only or p.dist in args.only]
    if not packages:
        print(
            f"error: --only matched nothing (known: {[p.dist for p in PACKAGES]})", file=sys.stderr
        )
        return 2

    _announce_exclusions(packages)

    failed: list[str] = []
    skipped: list[str] = []
    for mode in ["bare", "all"] if args.mode == "both" else [args.mode]:
        label = "no extras" if mode == "bare" else "widest extra"
        print(f"\n=== {mode} (target Python {args.python}, {label}) ===")
        for pkg in packages:
            extra = f"[{pkg.widest_extra}]" if mode == "all" and pkg.widest_extra else ""
            ok, detail = check(pkg, mode, dist_dir, uv, args.python)
            if ok is None:
                print(f"  skip  {pkg.dist}{extra}: {detail}")
                skipped.append(f"{pkg.dist} ({mode}): {detail}")
            elif ok:
                print(f"  ok    {pkg.dist}{extra}: {detail}")
            else:
                print(f"  FAIL  {pkg.dist}{extra}: {detail}")
                failed.append(f"{pkg.dist} ({mode})")

    return _report(failed, skipped, args.python)


if __name__ == "__main__":
    sys.exit(main())

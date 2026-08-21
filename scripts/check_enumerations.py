#!/usr/bin/env python3
"""Assert that hand-maintained security enumerations still cover the tree.

Why this exists
---------------
Four reviews in a row found the same defect in four different subsystems: a
control is an explicit list, it is written against the one case that motivated
it, the codebase grows, and the list silently stops covering the new surface.

  * `verify-wheel-imports.py` enumerated 33 modules by hand.
  * `SENSITIVE_PATH_PATTERNS` enumerated 10 paths, and did not include the files
    added by the very commit that created the surface it guards.
  * `_PROTECTED_OPS` enumerated 5 route prefixes, and did not include
    `/v1/harness` — arbitrary code execution — mounted in the same PR.

Each was one line from being correct, and each was found by a human reading the
diff. That does not scale, and it is not what humans are good at. Enumerations
rot; properties do not. This script turns each list into a property checked
against the actual tree.

It is deliberately a *ratchet*, not a pass/fail gate, because the honest count
today is large: ~30 mounted routers perform mutating requests with no scope
entry. A zero baseline would block every PR on pre-existing gaps and would be
switched off within a week. So:

  * A gap that is already in the baseline is reported and tolerated.
  * A gap that is *not* in the baseline fails the build.
  * A baseline entry that is no longer a gap ALSO fails the build, which is what
    stops the file from becoming a permanent allowlist. Fix a gap, delete its
    line.

Every tolerated gap is printed on every run. A gate whose coverage silently
shrinks reads exactly like one that passes.

Usage
-----
    python scripts/check_enumerations.py                  # check
    python scripts/check_enumerations.py --write-baseline  # accept current state
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO / "quality" / "enumeration-baseline.json"

# Directories whose contents form the containment surface of a self-modifying
# system: the sandbox, the policy/scope engines, the security scanners, the CI
# definitions that gate all of it, and the ratchet baselines those gates read.
# A diff touching any of these should escalate to adversarial review.
SENSITIVE_ROOTS = (
    "packages/maistro-core/src/maistro/security/",
    "packages/maistro-core/src/maistro/policy/",
    "packages/maistro-core/src/maistro/capabilities/providers/",
    "packages/maistro-core/src/maistro/tools/sandbox/",
    "packages/maistro-core/src/maistro/graph/durable_runs/",
    "packages/maistro-rsi/src/maistro_rsi/sandbox/",
    # The measurement surface: task corpora, graders, and the train/holdout
    # split the loop is scored against. Editing your own exam is a containment
    # failure even though it touches no sandbox or security code.
    "packages/maistro-evolve/src/maistro_evolve/benchmarks/",
    ".github/workflows/",
    "quality/",
    "sbx/",
)

# Individual files on the containment surface that live OUTSIDE the directories
# above. Directory probes alone let any of these quietly fall off
# SENSITIVE_PATH_PATTERNS without failing the ratchet — including quarantine.py
# itself, i.e. the gate could lose protection from self-modification with a
# green build (Codex P2 on #263).
SENSITIVE_FILES = (
    "packages/maistro-rsi/src/maistro_rsi/quarantine.py",
    "packages/maistro-rsi/src/maistro_rsi/selfbranch.py",
    "packages/maistro-rsi/src/maistro_rsi/runner.py",
    "packages/maistro-rsi/src/maistro_rsi/coordinator.py",
    "packages/maistro-rsi/src/maistro_rsi/autorun.py",
    "packages/maistro-rsi/src/maistro_rsi/apply_agents.py",
    "packages/maistro-core/src/maistro/graph/depth.py",
    "packages/maistro-core/src/maistro/graph/nodes/agent_synth_dag.py",
    "packages/maistro-core/src/maistro/graph/nodes/agent_spawn_harness.py",
    # Promotion gates and the PR-opening path — what decides that a candidate
    # is good enough to keep, and what turns "kept" into a pull request.
    "packages/maistro-evolve/src/maistro_evolve/fitness.py",
    "packages/maistro-evolve/src/maistro_evolve/scorecard.py",
    "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py",
    "packages/maistro-rsi/src/maistro_rsi/harvest.py",
    # Score administration: which runners register, how results fold into
    # eval_scores, how scores become Elo, and the per-benchmark weights. Each
    # can move a score without touching the exam.
    "packages/maistro-evolve/src/maistro_evolve/harness.py",
    "packages/maistro-evolve/src/maistro_evolve/cycle.py",
    "packages/maistro-evolve/src/maistro_evolve/tournament.py",
    "packages/maistro-evolve/src/maistro_evolve/types.py",
    # This file, and the vendoring scripts holding the vendored graders' pinned
    # digests. A ratchet outside the surface it protects can be edited in the
    # same diff as the list it checks, and the build stays green.
    "scripts/check_enumerations.py",
    "scripts/vendor_ifeval.py",
    "scripts/vendor_bfcl.py",
)

# maistro subpackages intentionally absent from CORE_PUBLIC_SURFACE, because they
# are gated behind extras: importing them from a bare install *should* fail, so
# listing them in the no-extras tier would make that tier fail by design. Both
# are still swept by the `all` tier, and `maistro.identity`'s guard is pinned by
# packages/maistro-core/tests/identity/test_extra_guard.py.
SURFACE_EXEMPT = {
    "maistro.cli": "typer/rich, behind the `tui` extra",
    "maistro.identity": "bip-utils/pynacl, behind the `identity` extra",
}

# Route prefixes that legitimately need no scope entry. Two kinds live here:
# identity/bootstrap machinery, and the daily account's ordinary product
# surface — chat, personal tasks, notes, drafts, UI state. The middleware's
# permission model is assignment + per-task elevation; gating the primary UX
# behind elevation would train users to elevate reflexively, which destroys
# the signal elevation exists to create. Every entry names its reason so a
# reviewer can veto the classification, and anything NOT here and NOT scoped
# is a build-failing gap.
ROUTE_EXEMPT = {
    "/v1/auth": "login/register/elevate — the thing that establishes identity",
    "/v1/setup": "first-run bootstrap, public by design (see _PUBLIC_EXACT)",
    "/v1/setup-checklist": "personal first-run checklist dismissals",
    "/v1/chat": "the product's primary surface; admin is blocked from it, users live in it",
    "/v1/messages": "the user's own notification inbox",
    "/v1/tasks": "the user's own missions",
    "/v1/work-items": "the user's own drafts (suggest/clarify/confirm)",
    "/v1/memory": "the user's own memory entries (CRUD + reinforce/decay/contradict)",
    "/v1/program": "onboarding coaching (guidance/interview/pulse)",
    "/v1/confirms": "the human half of the agent-confirmation flow — it IS the control",
    "/v1/dag-runs": "run feedback/ratings; execution itself is scoped at /v1/dags",
    "/v1/dashboard": "personal UI layout",
    "/v1/profile": "the user's own profile",
    "/v1/design": "canvas/book content authoring",
    "/v1/canvas": "canvas visual evaluation (scoring, not execution)",
    "/v1/eval-judge": "run judging/scoring",
    "/v1/install": "bootstrap installer session state",
    "/v1/widgets": "dashboard widgets; /screenshot renders localhost with the CALLER's own session cookie",
    "/v1/cli": "creates an in-memory CLI session record only — no command execution in this router",
    "/v1/pm-fleet/distill": "telemetry recording; tool EXECUTION is scoped at /v1/pm-fleet/tools",
    "/v1/pm-fleet/topk": "telemetry recording",
}


@dataclass
class Gap:
    check: str
    item: str
    detail: str

    def key(self) -> str:
        return f"{self.check}::{self.item}"


# --- check A: mutating routes must carry a scope ---------------------------


def check_routes() -> tuple[list[Gap], str | None]:
    """Every mutating /v1/ route must resolve to a permission in _PROTECTED_OPS.

    Introspects the real FastAPI app rather than parsing decorators: the app is
    the authority on what is actually mounted, including routers mounted
    conditionally behind feature flags, and it reports the true method set.
    """
    backend = REPO / "packages" / "hive-conductor" / "backend"
    if not backend.is_dir():
        return [], "hive-conductor backend not present"

    # The backend imports sibling workspace packages that are not pip-installed
    # (pytest supplies them via `src` roots in pyproject.toml), so mirror that
    # here rather than requiring an editable install of all nine.
    for src_root in sorted((REPO / "packages").glob("*/src")):
        sys.path.insert(0, str(src_root))
    sys.path.insert(0, str(backend))
    os.environ.setdefault("CONDUCTOR_DATA_DIR", "/tmp/enum-check-data")
    try:
        from main import app  # type: ignore[import-not-found]
        from middleware.auth import (  # type: ignore[import-not-found]
            _PROTECTED_OPS,
            _PUBLIC_EXACT,
            _PUBLIC_PREFIXES,
            _matches_public_prefix,
        )
    except Exception as exc:  # pragma: no cover - reported, never swallowed
        # Deliberately not a silent skip: if this check cannot run, the build
        # should say so rather than print a green tick it has not earned.
        return [], f"could not import the app ({type(exc).__name__}: {exc})"

    def _is_public(path: str) -> bool:
        return path in _PUBLIC_EXACT or any(
            _matches_public_prefix(path, p) for p in _PUBLIC_PREFIXES
        )

    # A _PROTECTED_OPS entry on a path the middleware returns from EARLY as
    # public never executes: dispatch checks the public tables before the
    # permission table, so a "scoped" public route is unauthenticated in
    # practice (Codex P2 on #263: POST /v1/voice/intent). Model the bypass
    # instead of trusting the scope entry.
    gaps: dict[str, str] = {}
    for path, method in _mutating_v1_routes(app.routes):
        if _route_is_exempt(path):
            # Documented intentionally-public/unscoped prefixes (auth, setup).
            continue
        public = _is_public(path)
        scoped = _route_is_scoped(path, method, _PROTECTED_OPS)
        if public and scoped:
            gaps[f"{method} {path}"] = (
                "scope entry is INEFFECTIVE — middleware treats this path as "
                "public and never consults _PROTECTED_OPS"
            )
        elif public:
            gaps[f"{method} {path}"] = (
                "public mutating route — reachable without authentication "
                "(dispatch bypasses auth before the scope table)"
            )
        elif not scoped:
            gaps[f"{method} {path}"] = "mutating route with no _PROTECTED_OPS entry"
    return [Gap("routes", item, detail) for item, detail in sorted(gaps.items())], None


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _mutating_v1_routes(routes: object) -> list[tuple[str, str]]:
    """(path, method) for every mounted /v1/ route that changes state."""
    found: list[tuple[str, str]] = []
    for route in routes:  # type: ignore[union-attr]
        path = getattr(route, "path", None)
        if not path or not path.startswith("/v1/"):
            continue
        methods = getattr(route, "methods", None) or set()
        found.extend((path, method) for method in sorted(methods & _MUTATING_METHODS))
    return found


def _route_is_exempt(path: str) -> bool:
    """Boundary-safe match against ROUTE_EXEMPT.

    Raw startswith let "/v1/setup" also exempt sibling routers like
    "/v1/setup-checklist/..." — absent from both the gaps and the baseline
    even though only the first-run setup router is documented as exempt
    (Codex P2 on #263). A prefix exempts itself and its sub-paths, nothing
    that merely shares its spelling.
    """
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ROUTE_EXEMPT)


def _route_is_scoped(path: str, method: str, protected: dict[str, dict[str, str]]) -> bool:
    """True if this route needs no scope entry, or already resolves to one.

    The _PROTECTED_OPS match stays raw startswith ON PURPOSE: that is exactly
    how middleware._required_permission matches at runtime, and this checker
    must model enforcement as it is, not as it ought to be.
    """
    if path.endswith("/invoke"):
        return True  # documented exemption in _required_permission
    if _route_is_exempt(path):
        return True
    return any(path.startswith(prefix) for prefix in protected.get(method, {}))


# --- check B: the sensitive-path list must cover the sensitive dirs --------


def check_sensitive_paths() -> tuple[list[Gap], str | None]:
    """Every file under a containment-surface directory must escalate.

    Probes go through the REAL matcher (`matches_sensitive_pattern`), not a
    local reimplementation of it: an earlier version of this check replicated
    the substring logic, which meant the gate could pass while asserting
    semantics the quarantine no longer used.
    """
    src = REPO / "packages" / "maistro-rsi" / "src" / "maistro_rsi" / "quarantine.py"
    if not src.is_file():
        return [], "quarantine.py not present"

    sys.path.insert(0, str(REPO / "packages" / "maistro-rsi" / "src"))
    try:
        from maistro_rsi.quarantine import matches_sensitive_pattern
    except Exception as exc:  # pragma: no cover
        return [], f"could not import quarantine ({type(exc).__name__}: {exc})"

    try:
        from maistro_rsi.quarantine import SENSITIVE_PATH_PATTERNS
    except Exception as exc:  # pragma: no cover
        return [], f"could not import quarantine patterns ({type(exc).__name__}: {exc})"

    gaps: list[Gap] = []
    for root in SENSITIVE_ROOTS:
        root_dir = REPO / root
        if not root_dir.is_dir():
            # A configured root that stops existing is a gap, not a silent
            # skip: either the surface moved (update this list) or something
            # deleted a containment directory (worth a red build either way).
            gaps.append(Gap("sensitive_paths", root, "configured sensitive root does not exist"))
            continue
        # One representative file path per directory: if the directory is
        # unmatched by the real matcher, every file under it is unmatched.
        probe = f"{root}__probe__.py"
        if not matches_sensitive_pattern(probe):
            gaps.append(
                Gap(
                    "sensitive_paths",
                    root,
                    "containment-surface directory not matched by SENSITIVE_PATH_PATTERNS",
                )
            )
    for file_path in SENSITIVE_FILES:
        if not (REPO / file_path).is_file():
            gaps.append(
                Gap("sensitive_paths", file_path, "configured sensitive file does not exist")
            )
            continue
        if not matches_sensitive_pattern(file_path):
            gaps.append(
                Gap(
                    "sensitive_paths",
                    file_path,
                    "containment-surface file not matched by SENSITIVE_PATH_PATTERNS",
                )
            )
    gaps.extend(_dead_patterns(SENSITIVE_PATH_PATTERNS))
    return gaps, None


def _dead_patterns(patterns: tuple[str, ...]) -> list[Gap]:
    """Patterns that match nothing in the tree.

    The inverse direction of the coverage probes above, and the gate's own
    blind spot until an external review caught it: `maistro_rsi/durable_runs/`
    sat in SENSITIVE_PATH_PATTERNS matching a directory that does not exist —
    the checker verified files-are-covered, never patterns-match-something, so
    a typo'd or bit-rotted pattern protected nothing while reading as if it
    did.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    gaps: list[Gap] = []
    for pattern in patterns:
        if pattern.endswith("/"):
            alive = any(p.startswith(pattern) or f"/{pattern}" in p for p in tracked)
        else:
            alive = any(p == pattern or p.endswith(f"/{pattern}") for p in tracked)
        if not alive:
            gaps.append(
                Gap(
                    "sensitive_paths",
                    f"pattern:{pattern}",
                    "SENSITIVE_PATH_PATTERNS entry matches no tracked file",
                )
            )
    return gaps


# --- check C: the documented public surface must be complete ---------------


def check_core_surface() -> tuple[list[Gap], str | None]:
    """Every importable maistro subpackage must be in CORE_PUBLIC_SURFACE.

    This is the check that would have caught `maistro.identity` being absent
    from the list in the script whose own docstring names it.
    """
    spec_path = REPO / "scripts" / "verify-wheel-imports.py"
    if not spec_path.is_file():
        return [], "verify-wheel-imports.py not present"

    surface = _literal_list(spec_path, "CORE_PUBLIC_SURFACE")
    if not surface:
        return [], "could not read CORE_PUBLIC_SURFACE from verify-wheel-imports.py"

    core_src = REPO / "packages" / "maistro-core" / "src" / "maistro"
    if not core_src.is_dir():
        return [], "maistro-core src not present"

    return [
        Gap("core_surface", name, "importable module absent from CORE_PUBLIC_SURFACE")
        for name in _importable_children(core_src, prefix="maistro")
        if name not in surface and name not in SURFACE_EXEMPT
    ], None


def _literal_list(path: Path, name: str) -> set[str]:
    """Read a module-level list literal by name, via AST.

    Parsed rather than imported or exec'd: the target is a CLI with module-level
    dataclasses, so executing it here would run unrelated code and couple this
    check to that file's imports.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    return set()


def _importable_children(root: Path, *, prefix: str) -> list[str]:
    """Dotted names of the importable modules and subpackages directly under root."""
    names: list[str] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(("_", ".")):
            continue
        if child.is_dir():
            if (child / "__init__.py").is_file():
                names.append(f"{prefix}.{child.name}")
        elif child.suffix == ".py":
            names.append(f"{prefix}.{child.stem}")
    return names


CHECKS = {
    "routes": check_routes,
    "sensitive_paths": check_sensitive_paths,
    "core_surface": check_core_surface,
}


def load_baseline() -> dict[str, str]:
    if not BASELINE_PATH.is_file():
        return {}
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return dict(data.get("tolerated", {}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current gaps as tolerated (review the diff before committing)",
    )
    args = parser.parse_args()

    all_gaps: list[Gap] = []
    unavailable: list[tuple[str, str]] = []
    for name, fn in CHECKS.items():
        gaps, reason = fn()
        if reason:
            unavailable.append((name, reason))
        all_gaps.extend(gaps)

    if args.write_baseline:
        return _write_baseline(all_gaps)

    baseline = load_baseline()
    current = {g.key(): g for g in all_gaps}
    new_gaps = [g for k, g in sorted(current.items()) if k not in baseline]
    fixed = sorted(k for k in baseline if k not in current)

    _report(baseline, current, unavailable, fixed, new_gaps)

    if new_gaps or fixed or unavailable:
        return 1
    print("\nno new enumeration gaps")
    return 0


def _write_baseline(all_gaps: list[Gap]) -> int:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            "Gaps in hand-maintained security enumerations that predate "
            "scripts/check_enumerations.py. This is a ratchet, not an "
            "allowlist: a NEW gap fails the build, and so does a stale "
            "entry here. Fix a gap, delete its line. Do not add entries "
            "without fixing or filing the underlying gap."
        ),
        "tolerated": {g.key(): g.detail for g in sorted(all_gaps, key=Gap.key)},
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(all_gaps)} tolerated gaps to {BASELINE_PATH.relative_to(REPO)}")
    return 0


def _report(
    baseline: dict[str, str],
    current: dict[str, Gap],
    unavailable: list[tuple[str, str]],
    fixed: list[str],
    new_gaps: list[Gap],
) -> None:
    # Report what is tolerated, always. Silence here is how a shrinking gate
    # passes for a healthy one.
    if baseline:
        print(f"tolerated (baselined) gaps: {len(baseline) - len(fixed)}")
        for key in sorted(baseline):
            if key in current:
                print(f"  · {key}")

    if unavailable:
        print("\nCHECKS THAT COULD NOT RUN (treated as failure):")
        for name, reason in unavailable:
            print(f"  ! {name}: {reason}")

    if fixed:
        print(f"\nSTALE BASELINE ENTRIES ({len(fixed)}) — these are now covered:")
        for key in fixed:
            print(f"  ✓ {key}")
        print("Delete them from quality/enumeration-baseline.json to lock the fix in.")

    if new_gaps:
        print(f"\nNEW ENUMERATION GAPS ({len(new_gaps)}):")
        for gap in new_gaps:
            print(f"  ✗ [{gap.check}] {gap.item}\n      {gap.detail}")


if __name__ == "__main__":
    sys.exit(main())

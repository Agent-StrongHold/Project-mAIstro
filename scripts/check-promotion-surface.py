#!/usr/bin/env python3
"""Every module the promotion path reaches must escalate to adversarial review.

Why this exists
---------------
`SENSITIVE_PATH_PATTERNS` decides which self-modifications need adversarial
review on top of Warden and the full test suite. It was a hand-written list,
and it grew the way hand-written lists grow: one entry at a time, each added
after a human noticed the omission in a diff.

#303 found three more that way. `maistro_rsi/local_loop.py` fast-forwards the
baseline branch -- it *is* promotion. `maistro_rsi/merge.py` decides which
candidates land. `maistro_rsi/code_fixer.py` drives the builders agent over a
candidate's worktree. None of the three matched a pattern, so a candidate could
edit the code that promotes it and clear the gate on Warden alone.

The omissions are not the defect. The method is. So the requirement is derived
here instead of enumerated: start at the modules that execute candidate code,
compute acceptance, mutate the baseline, open a pull request, or decide what is
protected, walk the first-party import graph out of them, and require every
module reached to be on the containment surface.

That is a property, and properties do not rot. A candidate that adds a wrapper
module and routes promotion through it is caught, because for the wrapper to
have any effect something in the closure must import it -- which puts it in the
closure. A rename is caught for the same reason: the graph follows imports, not
paths.

The baseline
------------
Some modules in the closure are ordinary infrastructure -- an HTTP client, a
quota counter, a settings object. Escalating every diff that touches those
would make escalation mean nothing, which is the failure mode this gate is
supposed to prevent one level up. Those are recorded in
`quality/promotion-surface-baseline.json`, each with a written reason, and the
ledger is checked in both directions:

  * a reachable module that is neither protected nor baselined fails the build;
  * a baselined module that has since become protected fails the build, so the
    file cannot silently become a permanent allowlist;
  * a baselined module that is no longer reachable fails the build, so a stale
    entry cannot hide a later re-entry.

Usage
-----
    python scripts/check-promotion-surface.py                  # check
    python scripts/check-promotion-surface.py --write-baseline # accept current
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO / "quality" / "promotion-surface-baseline.json"
#: The containment-surface classifier. A fixed sibling of this script rather
#: than a function of the tree being audited, so a test that redirects `REPO`
#: at a fixture tree still consults the real matcher -- which is the whole
#: point of loading it instead of reimplementing it.
CLASSIFIER = (
    Path(__file__).resolve().parent.parent
    / "packages"
    / "maistro-rsi"
    / "src"
    / "maistro_rsi"
    / "sensitive_paths.py"
)

# The entry points of the promotion and execution path, each named with the
# capability that puts it here. These are the roots of the walk, so an omission
# here is the one thing the derivation cannot fix for itself -- which is why
# every root is checked for existence and a missing one is a hard failure
# rather than a skipped root.
PROMOTION_ROOTS: dict[str, str] = {
    "maistro_rsi.local_loop": "fast-forwards the baseline branch (mutates the baseline)",
    "maistro_rsi.merge": "decides which candidate diffs land together",
    "maistro_rsi.code_fixer": "drives the builders agent over a candidate worktree",
    "maistro_rsi.candidate_fitness": "computes the acceptance verdict",
    "maistro_rsi.selfbranch": "writes the self-modification branch",
    "maistro_rsi.harvest": "turns a promotion into a pull request",
    "maistro_rsi.quarantine": "decides whether a diff needs adversarial review",
    "maistro_rsi.sensitive_paths": "holds the protected-path classifier itself",
    "maistro_rsi.autorun": "drives the cycle that promotes",
    "maistro_rsi.coordinator": "schedules and sequences cycles",
    "maistro_rsi.runner": "builds the command each cycle executes",
    "maistro_rsi.apply_agents": "applies agent definitions into the baseline",
    "maistro_evolve.fitness": "holds the breeding and promotion thresholds",
    "maistro_evolve.scorecard": "renders the score a promotion decision reads",
}

#: Where first-party source lives. A module outside these is third-party and is
#: not walked -- its supply-chain risk is `pip-audit`'s problem, not this
#: gate's, and following it would drag in the standard library.
SOURCE_ROOTS = ("packages/*/src",)


@dataclass(frozen=True)
class Finding:
    module: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}  ({self.module}) -- {self.detail}"


def _matcher():
    """The real classifier, not a local reimplementation of it.

    `scripts/check_enumerations.py` learned that lesson the hard way: it once
    replicated the substring logic, so the gate could pass while asserting
    semantics the quarantine no longer used.

    Loaded **by file path**, not as `maistro_rsi.sensitive_paths`. The package
    import runs `maistro_rsi/__init__.py`, which imports `coordinator`, which
    imports `structlog` -- so the dotted form needs the workspace installed, and
    this gate runs in the lint job where it is not. `sensitive_paths` itself
    imports nothing outside the standard library, which is what makes loading it
    on its own possible; `test_the_gate_loads_the_matcher_without_the_workspace
    _installed` is what keeps that true.
    """
    spec = importlib.util.spec_from_file_location("_maistro_sensitive_paths", CLASSIFIER)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable for a real file
        msg = f"cannot load the containment-surface classifier from {CLASSIFIER}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.matches_sensitive_pattern


def index_modules() -> dict[str, Path]:
    """Map every first-party dotted module name to its file.

    A package directory maps to its ``__init__.py``, so ``import pkg`` and
    ``from pkg.mod import x`` resolve to different files rather than one
    swallowing the other.
    """
    modules: dict[str, Path] = {}
    for pattern in SOURCE_ROOTS:
        for root in sorted(REPO.glob(pattern)):
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.py")):
                parts = list(path.relative_to(root).parts)
                if parts[-1] == "__init__.py":
                    parts.pop()
                else:
                    parts[-1] = parts[-1].removesuffix(".py")
                if parts:
                    modules.setdefault(".".join(parts), path)
    return modules


def imported_names(path: Path) -> set[str]:
    """Every absolute dotted name a module imports, aliases resolved away.

    Read from the AST rather than by importing: this runs in the lint job with
    no package installed, and executing a module to find out what it imports
    would run the promotion code to ask whether it is protected.

    ``import x as y`` records ``x`` because the AST carries the real name and
    discards the alias, so renaming on import evades nothing. ``from p import
    m`` records both ``p`` and ``p.m``, because only the module index can say
    which of the two is a module and which is a symbol inside one.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports resolve within a package already in the closure,
            # so their targets are reached through the package's own file.
            if node.level or not node.module:
                continue
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _resolve(name: str, modules: dict[str, Path]) -> str | None:
    """The longest prefix of ``name`` that is a first-party module."""
    candidate = name
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def reachable(roots: Iterable[str], modules: dict[str, Path]) -> set[str]:
    seen: set[str] = set()
    stack = [root for root in roots if root in modules]
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        for name in imported_names(modules[module]):
            target = _resolve(name, modules)
            if target is not None and target not in seen:
                stack.append(target)
    return seen


def load_baseline() -> dict[str, str]:
    if not BASELINE_PATH.is_file():
        return {}
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return dict(data.get("tolerated", {}))


def _missing_roots(modules: dict[str, Path]) -> list[Finding]:
    """A declared root that no longer resolves.

    Silence here would be the worst failure this gate has: the walk would
    simply start somewhere smaller and report a clean tree.
    """
    return [
        Finding(root, "-", f"declared promotion root does not exist ({why})")
        for root, why in sorted(PROMOTION_ROOTS.items())
        if root not in modules
    ]


def _symlinked_sources(closure: set[str], modules: dict[str, Path]) -> list[Finding]:
    """A source file in the closure that is a symlink.

    A symlink lets one path's content be edited under another path's name, so
    the path a diff declares stops being the path a reviewer classified. There
    are none today; the check exists so that adding one is a decision somebody
    makes on purpose.
    """
    findings = []
    for module in sorted(closure):
        path = modules[module]
        if path.is_symlink():
            rel = path.relative_to(REPO).as_posix()
            findings.append(Finding(module, rel, "source file is a symlink"))
    return findings


def _coverage(
    closure: set[str], modules: dict[str, Path], baseline: dict[str, str], matches
) -> tuple[list[Finding], list[Finding], list[str]]:
    """Uncovered modules, stale baseline entries, and the tolerated list."""
    uncovered: list[Finding] = []
    tolerated: list[str] = []
    stale: list[Finding] = []

    for module in sorted(closure):
        rel = modules[module].relative_to(REPO).as_posix()
        protected = matches(rel)
        if protected and rel in baseline:
            stale.append(Finding(module, rel, "baselined but now protected -- delete the entry"))
        elif protected:
            continue
        elif rel in baseline:
            tolerated.append(f"{rel} -- {baseline[rel]}")
        else:
            uncovered.append(
                Finding(module, rel, "reachable from the promotion path and not protected")
            )

    reachable_paths = {modules[m].relative_to(REPO).as_posix() for m in closure}
    for rel in sorted(set(baseline) - reachable_paths):
        stale.append(Finding("-", rel, "baselined but no longer reachable -- delete the entry"))

    return uncovered, stale, tolerated


def audit() -> tuple[list[Finding], list[str]]:
    modules = index_modules()
    findings = _missing_roots(modules)
    if findings:
        # Walking from a truncated root set would report a clean tree, which is
        # a worse answer than no answer.
        return findings, []

    closure = reachable(PROMOTION_ROOTS, modules)
    findings.extend(_symlinked_sources(closure, modules))
    uncovered, stale, tolerated = _coverage(closure, modules, load_baseline(), _matcher())
    findings.extend(uncovered)
    findings.extend(stale)
    return findings, tolerated


def write_baseline() -> int:
    modules = index_modules()
    closure = reachable(PROMOTION_ROOTS, modules)
    matches = _matcher()
    existing = load_baseline()
    tolerated = {}
    for module in sorted(closure):
        rel = modules[module].relative_to(REPO).as_posix()
        if not matches(rel):
            tolerated[rel] = existing.get(rel, "TODO: state why this need not escalate")
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "Modules reachable from the promotion/execution path that deliberately "
                    "do not escalate to adversarial review. Every entry needs a reason. "
                    "See scripts/check-promotion-surface.py."
                ),
                "tolerated": tolerated,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {BASELINE_PATH.relative_to(REPO)} with {len(tolerated)} tolerated module(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    if args.write_baseline:
        return write_baseline()

    findings, tolerated = audit()

    # Printed on every run, pass or fail: a gate whose tolerated set silently
    # grows reads exactly like one that has nothing to tolerate.
    print(f"promotion surface: {len(tolerated)} tolerated module(s)")
    for line in tolerated:
        print(f"  tolerated: {line}")

    if findings:
        print(f"\n{len(findings)} promotion-surface gap(s):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nEither add a pattern to maistro_rsi/sensitive_paths.py, or record the "
            "module in quality/promotion-surface-baseline.json with a reason.",
            file=sys.stderr,
        )
        return 1

    print("promotion surface: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

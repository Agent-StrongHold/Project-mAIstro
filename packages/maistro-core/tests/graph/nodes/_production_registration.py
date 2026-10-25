"""The reconciled production registration universe for the composition guards.

Issue #1082's residual audit found the guards' input hole: both composition
sweeps derived their universe from the process-local `list_kinds()` at
collection time, which only proves whatever registration modules the current
pytest process happened to import. The CI core job never imports
`maistro_design.creative_graph`, so its eleven `creative.*` kinds were
invisible to both sweeps even though `scripts/check-reachability.py` counts
the module as reachable production source — a future authority declaration in
that production module would have escaped the generic guard through
import/collection order alone.

This helper reconciles three independent views into one universe:

1. **Source identities** — every production-shaped Python file under
   `packages/*/src` whose AST actually calls `register_node` (decorators
   included), using `check-reachability`'s own
   `_all_package_python_files` classification so a new directory cannot
   vanish from the scan. Prose mentions in docstrings and comments do not
   count; test-shaped files (`tests/` trees, `test_*` modules) never do —
   fixture registrations are not production proof.
2. **The reachability ledger** — `quality/reachability-baseline.json`, kept
   accurate by the existing reachability gate (a newly unreachable module
   must be baselined; a baselined module that becomes reachable fails that
   gate until pruned). A registration module that is reachable must be
   *loaded* below; one classified unreachable must carry a reviewed
   disposition in `quality/reachability-dispositions.json`, and its kinds
   stay out of the proof — production processes never construct them.
3. **The registry itself** — after the reachable registration modules are
   imported, every non-`test.*` registered kind must have been defined in
   one of them. A kind registered from anywhere else (a fixture helper, an
   unreachable module) cannot pass as production composition proof.

The imports happen when this module is imported, so no unrelated test
module's registration (or absence of one) can change what the sweeps prove.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from maistro.graph.nodes import get_node, list_kinds

#: tests/graph/nodes/_production_registration.py -> the repository root.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]

_REACHABILITY_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "check-reachability.py"
_REACHABILITY_BASELINE: Final[Path] = _REPO_ROOT / "quality" / "reachability-baseline.json"
_REACHABILITY_DISPOSITIONS: Final[Path] = _REPO_ROOT / "quality" / "reachability-dispositions.json"


_reachability_module_cache: dict[str, object] = {}


def _load_reachability_module() -> object:
    """Import `scripts/check-reachability.py` for its source-universe rules.

    The script is repository machinery, not per-tree data: even a synthetic
    tree under test is classified by the real rules, the way
    `tests/test_reachability_source_universe.py` runs the real script against
    tmp trees. A distinct module name keeps this copy out of the reachability
    suite's own when one session collects both.
    """
    cached = _reachability_module_cache.get("module")
    if cached is not None:
        return cached
    script = _REPO_ROOT / "scripts" / "check-reachability.py"
    spec = importlib.util.spec_from_file_location("_composition_reachability", script)
    if spec is None or spec.loader is None:  # pragma: no cover - load mechanism
        raise RuntimeError(f"cannot load reachability script at {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _reachability_module_cache["module"] = module
    return module


def _registration_site(path: Path) -> bool:
    """Whether the file's code actually registers a node kind.

    AST-based so the many prose mentions of `register_node` in docstrings and
    comments (the registry's own module docstring included) never fabricate a
    registration module.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - production source parses
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "register_node":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "register_node":
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "register_node":
                    return True
                if isinstance(decorator, ast.Attribute) and decorator.attr == "register_node":
                    return True
    return False


def _dotted_module(path: Path, root: Path) -> str | None:
    """The importable name of a file under a packaged `src` root, or `None`.

    `packages/<dist>/src/a/b/mod.py` becomes `a.b.mod`; a package
    `__init__.py` maps to its package. `None` means the registration site
    sits outside every packaged src root — the caller must fail loudly
    rather than silently sweep less.
    """
    parts = path.relative_to(root).parts
    if "src" not in parts:
        return None
    segments = list(parts[parts.index("src") + 1 :])
    if not segments:
        return None
    if segments[-1] == "__init__.py":
        segments = segments[:-1]
    else:
        segments[-1] = segments[-1][: -len(".py")]
    if not segments:
        return None
    return ".".join(segments)


def scan_registration_modules(root: Path = _REPO_ROOT) -> dict[str, Path]:
    """Every production source file that registers node kinds, by import name.

    Test-shaped files are already outside the universe: the reachability
    classification this builds on excludes `tests/` trees and `test_*`
    modules, which is exactly the rule that keeps fixture registrations from
    satisfying the production proof.
    """
    reachability = _load_reachability_module()
    modules: dict[str, Path] = {}
    outside_src: list[Path] = []
    for path in sorted(reachability._all_package_python_files(root)):
        if not _registration_site(path):
            continue
        dotted = _dotted_module(path, root)
        if dotted is None:
            outside_src.append(path)
            continue
        modules[dotted] = path
    if outside_src:
        raise RuntimeError(
            "node registration outside a packaged src root cannot be swept by dotted "
            "import name; load it through the catalog sweep or extend this guard's "
            "mapping: " + ", ".join(str(p.relative_to(root)) for p in outside_src)
        )
    return modules


def unreachable_identities(root: Path = _REPO_ROOT) -> frozenset[str]:
    """The reviewed unreachable-module ledger, verbatim."""
    data = json.loads(_baseline_path(root).read_text(encoding="utf-8"))
    return frozenset(data["unreachable"])


def dispositioned_modules(root: Path = _REPO_ROOT) -> frozenset[str]:
    """Module identities a reviewed reachability disposition accounts for."""
    data = json.loads(_dispositions_path(root).read_text(encoding="utf-8"))
    dispositioned: set[str] = set()
    for group in data.get("groups", []):
        dispositioned.update(group.get("modules", []))
    return frozenset(dispositioned)


def _baseline_path(root: Path) -> Path:
    return root / "quality" / "reachability-baseline.json"


def _dispositions_path(root: Path) -> Path:
    return root / "quality" / "reachability-dispositions.json"


@dataclass(frozen=True)
class Reconciliation:
    """The three views aligned, with every mismatch made explicit."""

    #: Every production source registration site: import name -> file.
    registration_modules: dict[str, Path]
    #: The import names actually loaded into this process.
    loaded: frozenset[str]
    #: Reachable registration modules the loader did not import: the hole the
    #: 2026-10-03 audit found, surfaced as data instead of passing silently.
    reachable_omitted: frozenset[str]
    #: Registration modules classified unreachable with no reviewed
    #: disposition: a justified difference must be recorded, not silent.
    unreachable_unreviewed: frozenset[str]
    #: Every non-`test.*` registered kind -> the module that defined its class.
    production_kinds: dict[str, str]
    #: Production kinds whose defining module was never loaded by the guard:
    #: a kind swept without a production source identity is not proof.
    kinds_from_outside_loaded: frozenset[str]


def reconcile(root: Path, loaded: Iterable[str]) -> Reconciliation:
    """Align the source scan, the ledger and the live registry.

    `root` is parameterized so the negative cases can run this exact
    reconciliation against a synthetic tree; the production sweeps pass the
    real repository root and the modules :data:`LOADED_REGISTRATION_MODULES`
    imported.
    """
    registration_modules = scan_registration_modules(root)
    unreachable = unreachable_identities(root)
    dispositioned = dispositioned_modules(root)
    loaded_set = frozenset(loaded)

    reachable = frozenset(registration_modules) - unreachable
    production_kinds = {
        kind: get_node(kind).__module__ for kind in list_kinds() if not kind.startswith("test.")
    }
    return Reconciliation(
        registration_modules=registration_modules,
        loaded=loaded_set,
        reachable_omitted=reachable - loaded_set,
        unreachable_unreviewed=frozenset(
            module
            for module in frozenset(registration_modules) & unreachable
            if module not in dispositioned
        ),
        production_kinds=production_kinds,
        kinds_from_outside_loaded=frozenset(
            kind for kind, module in production_kinds.items() if module not in loaded_set
        ),
    )


def production_kinds(root: Path = _REPO_ROOT) -> dict[str, str]:
    """Every non-`test.*` registered kind -> the module that defined it.

    Callers must have imported this module first: the returned map is only
    the reconciled universe once :data:`LOADED_REGISTRATION_MODULES` has been
    computed (which happens at import time)."""
    return {
        kind: get_node(kind).__module__ for kind in list_kinds() if not kind.startswith("test.")
    }


def _import_reachable_registrations(root: Path = _REPO_ROOT) -> frozenset[str]:
    """Load every reachable production registration module, and only those.

    Importing the module *is* the production loading: the core leaf modules
    self-register at import through the catalog's own eager sweep, and
    `maistro_design.creative_nodes` executes the same `register_node` calls
    production runs when the Conductor imports `creative_graph`. Loading
    here — at this module's import time — is what makes the guards
    independent of test collection order.
    """
    reachable = sorted(frozenset(scan_registration_modules(root)) - unreachable_identities(root))
    for dotted in reachable:
        importlib.import_module(dotted)
    return frozenset(reachable)


#: The production registration modules this process has loaded. Importing
#: this helper is what puts the reconciled universe into the registry.
LOADED_REGISTRATION_MODULES: Final[frozenset[str]] = _import_reachable_registrations()

"""The composition guards sweep exactly the production registration universe.

The 2026-10-03 residual audit of #1082 found the guards' input hole: both
sweeps derived their universe from process-local `list_kinds()`, and the CI
core job's pytest process never imports the design registration path — so the
eleven `creative.*` kinds `scripts/check-reachability.py` counts as reachable
production source were invisible to both sweeps, and a future authority
declaration there would have escaped the generic guard through collection
order alone.

These tests pin the reconciliation itself: source identities (AST
`register_node` sites under the reviewed production source universe), the
reachability ledger (`quality/reachability-baseline.json`, kept accurate by
the reachability gate) and the live registry must agree after
:mod:`_production_registration` loads the reachable registration modules. The
negative cases run the same reconciliation against synthetic trees: a
reachable registration omitted from loading is detected, an unreachable one
without a reviewed disposition is detected, and test-shaped registrations
stay outside the universe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from maistro.graph.nodes import get_node, list_kinds

from ._production_registration import (
    _REPO_ROOT,
    LOADED_REGISTRATION_MODULES,
    Reconciliation,
    dispositioned_modules,
    reconcile,
    scan_registration_modules,
    unreachable_identities,
)

_CREATIVE_MODULE = "maistro_design.creative_nodes"


def _real_reconciliation() -> Reconciliation:
    return reconcile(_REPO_ROOT, LOADED_REGISTRATION_MODULES)


# --- the real tree: the three views must agree --------------------------------------


def test_the_reconciliation_is_clean_on_the_real_tree() -> None:
    """Every reachable registration module is loaded, every unreachable one
    has a reviewed disposition, and no production kind is defined outside the
    loaded set. One assertion per mismatch class, so a regression names its
    own hole."""
    report = _real_reconciliation()

    assert not report.reachable_omitted, (
        "reachable production registration modules the guard did not load — the "
        f"#1082 selection hole, detected: {sorted(report.reachable_omitted)}"
    )
    assert not report.unreachable_unreviewed, (
        "registration modules classified unreachable without a reviewed reachability "
        f"disposition: {sorted(report.unreachable_unreviewed)}"
    )
    assert not report.kinds_from_outside_loaded, (
        "production kinds defined outside the loaded registration modules — not "
        f"production composition proof: {sorted(report.kinds_from_outside_loaded)}"
    )
    assert report.loaded, "the guard loaded no production registration modules at all"
    assert report.production_kinds, "the guard proved no production kinds at all"


def test_the_creative_kinds_enter_through_their_real_production_module() -> None:
    """The audit's proof requirement: the eleven `creative.*` kinds are in the
    universe through `maistro_design.creative_nodes` — the module production
    executes when the Conductor imports `creative_graph` — not through a
    hand-maintained copy of today's kind list."""
    report = _real_reconciliation()

    assert _CREATIVE_MODULE in report.loaded
    creative = {
        kind: module
        for kind, module in report.production_kinds.items()
        if module == _CREATIVE_MODULE
    }
    assert len(creative) == 11, sorted(creative)
    assert all(kind.startswith("creative.") for kind in creative), sorted(creative)
    # And the source scan found the registrations where production writes them.
    assert report.registration_modules[_CREATIVE_MODULE] == (
        _REPO_ROOT / "packages" / "maistro-design" / "src" / "maistro_design" / "creative_nodes.py"
    )


def test_the_core_catalog_kinds_are_in_the_universe_through_the_sweep() -> None:
    """The `maistro.graph.nodes` package sweep remains the loading path for the
    core kinds: their defining modules are reachable registration sites the
    guard loaded, so the #1079/#147/#1193 regressions keep their coverage."""
    report = _real_reconciliation()

    core = {
        kind: module
        for kind, module in report.production_kinds.items()
        if module.startswith("maistro.graph.nodes.")
    }
    assert "llm.summarize" in core and "agent.delegate_remote" in core
    assert "agent.synth_dag" in core
    assert set(core.values()) <= report.loaded


def test_the_unreachable_registration_module_stays_out_of_the_proof() -> None:
    """`maistro_design.nodes` registers `design.orchestrate` and
    `design.consistency_eval`, but the reviewed `design-node` disposition
    records that no production process ever imports it — the catalog sweep
    cannot load it and the kinds are never registered. The guard must neither
    sweep those kinds as production proof nor silently drop the module: the
    exclusion has to be the reviewed one."""
    report = _real_reconciliation()

    assert "maistro_design.nodes" not in report.loaded
    assert "maistro_design.nodes" in unreachable_identities(_REPO_ROOT)
    assert "maistro_design.nodes" in dispositioned_modules(_REPO_ROOT)
    assert not {kind for kind in report.production_kinds if kind.startswith("design.")}
    # And the kinds stay unregistered in a process that only loads production
    # modules: nothing above ever imported the unreachable module.
    import pytest

    with pytest.raises(KeyError):
        get_node("design.orchestrate")


def test_the_composition_sweeps_use_this_universe() -> None:
    """The two existing sweeps and the reconciled universe must be the same
    set: neither sweep can silently shrink to a subset (or balloon with
    process-local fixture kinds) without failing here."""
    from .test_container_node_composition import _kinds_declaring_authorities
    from .test_node_composition import shipped_kinds

    production = sorted(_real_reconciliation().production_kinds)
    assert shipped_kinds() == production
    declaring = _kinds_declaring_authorities()
    assert set(declaring) <= set(production)
    # The declaring sweep is not the whole story: kinds without authorities
    # (the creative eleven among them) participate through the universe.
    assert set(production) - set(declaring), "every production kind declares an authority?"


# --- negative cases on synthetic trees ----------------------------------------------


def _synthetic_repo(
    tmp_path: Path,
    *,
    registration_files: dict[str, str],
    unreachable: set[str],
    dispositioned: set[str],
) -> Path:
    """A minimal tree the reconciliation functions accept as `root`."""
    root = tmp_path / "repo"
    for rel, body in registration_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    quality = root / "quality"
    quality.mkdir(parents=True, exist_ok=True)
    (quality / "reachability-baseline.json").write_text(
        json.dumps({"unreachable": sorted(unreachable)}), encoding="utf-8"
    )
    (quality / "reachability-dispositions.json").write_text(
        json.dumps({"groups": [{"id": "reviewed", "modules": sorted(dispositioned)}]}),
        encoding="utf-8",
    )
    return root


_REGISTRATION_BODY = (
    "from maistro.graph.nodes import register_node\n"
    "\n"
    "\n"
    "@register_node\n"
    "class _Synthetic:\n"
    "    pass\n"
)


def test_a_reachable_registration_omitted_from_loading_is_detected(tmp_path: Path) -> None:
    """The audit's hole, as data: a production registration module the guard
    never imported is reported instead of swept past."""
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": _REGISTRATION_BODY},
        unreachable=set(),
        dispositioned=set(),
    )

    scanned = scan_registration_modules(root)
    assert set(scanned) == {"x.reg"}

    report = reconcile(root, loaded=frozenset())
    assert report.reachable_omitted == frozenset({"x.reg"})


def test_loading_the_module_closes_the_same_hole(tmp_path: Path) -> None:
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": _REGISTRATION_BODY},
        unreachable=set(),
        dispositioned=set(),
    )

    report = reconcile(root, loaded={"x.reg"})

    assert not report.reachable_omitted


def test_an_unreachable_registration_without_a_disposition_is_detected(
    tmp_path: Path,
) -> None:
    """An exclusion nobody reviewed is not a justified difference."""
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": _REGISTRATION_BODY},
        unreachable={"x.reg"},
        dispositioned=set(),
    )

    report = reconcile(root, loaded=frozenset())

    assert report.unreachable_unreviewed == frozenset({"x.reg"})


def test_a_reviewed_disposition_justifies_the_exclusion(tmp_path: Path) -> None:
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": _REGISTRATION_BODY},
        unreachable={"x.reg"},
        dispositioned={"x.reg"},
    )

    report = reconcile(root, loaded=frozenset())

    assert not report.unreachable_unreviewed
    assert not report.reachable_omitted


def test_test_shaped_registrations_never_enter_the_universe(tmp_path: Path) -> None:
    """Fixture registrations are not production proof: the same files, inside
    a `tests/` tree or named `test_*`, are outside the source scan."""
    registration_files = {
        "packages/x/src/x/reg.py": _REGISTRATION_BODY,
        "packages/x/src/x/tests/reg.py": _REGISTRATION_BODY,
        "packages/x/src/x/test_reg.py": _REGISTRATION_BODY,
    }
    root = _synthetic_repo(
        tmp_path,
        registration_files=registration_files,
        unreachable=set(),
        dispositioned=set(),
    )

    scanned = scan_registration_modules(root)

    assert set(scanned) == {"x.reg"}


def test_a_registration_outside_a_packaged_src_root_fails_closed(tmp_path: Path) -> None:
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/flat_reg.py": _REGISTRATION_BODY},
        unreachable=set(),
        dispositioned=set(),
    )

    try:
        scan_registration_modules(root)
    except RuntimeError as exc:
        assert "flat_reg.py" in str(exc)
    else:  # pragma: no cover - the failure is the point
        raise AssertionError("a registration outside any src root was silently accepted")


# --- loading, not collection order, decides the universe ----------------------------


def test_a_bare_core_import_misses_what_loading_adds() -> None:
    """The audited selection difference, executed: a process that only imports
    the core catalog registers 19 kinds and no `creative.*`; importing the
    real design registration module is what adds them. Unrelated test
    collection order therefore cannot change what the guards prove — the
    helper performs the loading itself."""
    design_src = _REPO_ROOT / "packages" / "maistro-design" / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(design_src), *(p for p in [env.get("PYTHONPATH")] if p)]
    )
    probe = (
        "import json\n"
        "import maistro.graph.nodes as n\n"
        "bare = sorted(n.list_kinds())\n"
        f"import {_CREATIVE_MODULE}\n"
        "full = sorted(n.list_kinds())\n"
        "print(json.dumps({'bare': bare, 'added': sorted(set(full) - set(bare))}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    observed: dict[str, Any] = json.loads(proc.stdout)

    bare, added = set(observed["bare"]), set(observed["added"])
    assert not {kind for kind in bare if kind.startswith("creative.")}
    assert len(added) == 11
    # What loading adds is exactly what the reconciled universe attributes to
    # the design registration module.
    from_design = {
        kind
        for kind, module in _real_reconciliation().production_kinds.items()
        if module == _CREATIVE_MODULE
    }
    assert added == from_design
    assert from_design <= {kind for kind in list_kinds() if not kind.startswith("test.")}


def test_the_loaded_registration_modules_are_importable_production_modules() -> None:
    """Every loaded identity is a real module with a real file behind it —
    the guard loads production code, not registry entries a fixture made."""
    import importlib

    for dotted in sorted(LOADED_REGISTRATION_MODULES):
        module = importlib.import_module(dotted)
        assert getattr(module, "__file__", None), dotted

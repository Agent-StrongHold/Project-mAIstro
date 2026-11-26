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

#1864 adds the identity layer: :mod:`_registration_inventory` derives, from
source alone and without importing anything, which kind each reachable
registration expression binds to which class in which defining module and
checkout file — failing closed on registration forms it cannot attribute —
and the registry must bind exactly that. A fresh-process core-only load
fails that proof for the reachable design registrations even when the parent
pytest process has Design imported; the real production loaders pass it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

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
from ._registration_inventory import (
    ExpectedRegistration,
    UnsupportedRegistration,
    expected_in_module,
    expected_registrations,
    verify_identity_parity,
)

_CREATIVE_MODULE = "maistro_design.creative_nodes"

#: The statically expected inventory, derived once per session. Pure source
#: analysis: computing it imports no registration module and registers no
#: kind, so it can judge registries loaded independently of this helper.
_EXPECTED: dict[str, list[ExpectedRegistration]] = expected_registrations(_REPO_ROOT)


def _real_reconciliation() -> Reconciliation:
    return reconcile(_REPO_ROOT, LOADED_REGISTRATION_MODULES)


def _expected_registrations() -> list[ExpectedRegistration]:
    return [reg for regs in _EXPECTED.values() for reg in regs]


def _expected_for_kind(kind: str) -> ExpectedRegistration:
    hits = [reg for reg in _expected_registrations() if reg.kind == kind]
    assert len(hits) == 1, f"expected exactly one source registration for {kind!r}"
    return hits[0]


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


def test_the_design_orchestrate_kinds_are_production_kinds_through_nodes() -> None:
    """#2311 CONNECT for `design-node`: `maistro_design.nodes` is reachable via
    the package public surface (same pattern as explore/judge), so
    `design.orchestrate` and `design.consistency_eval` enter the reconciled
    production universe through that module — not as an unreachable exclusion.
    """
    report = _real_reconciliation()

    assert "maistro_design.nodes" in report.loaded
    assert "maistro_design.nodes" not in unreachable_identities(_REPO_ROOT)
    assert "maistro_design.nodes" not in dispositioned_modules(_REPO_ROOT)
    for kind in ("design.orchestrate", "design.consistency_eval"):
        assert report.production_kinds[kind] == "maistro_design.nodes"
        get_node(kind)  # registered in a process that only loads production modules


def test_the_governed_design_wave_kinds_are_production_kinds_through_their_own_modules() -> None:
    """#987 put the design wave on the canonical spine, so these kinds are
    production kinds — proven through their own loaded source identity.

    The governed explore/judge kinds are registered by reachable production
    modules, and the reconciled universe has to say so: each one is
    attributed to the module that defines it, and that module is one the
    guard actually loaded. (`design.orchestrate` / `design.consistency_eval`
    land through `maistro_design.nodes` — proven in the test above.)"""
    report = _real_reconciliation()

    for kind, module in (
        ("design.explore", "maistro_design.explore"),
        ("design.thesis", "maistro_design.explore"),
        ("design.judge", "maistro_design.model_judge"),
    ):
        assert report.production_kinds[kind] == module
        assert module in report.loaded
        assert module in report.registration_modules


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

#: A registration the identity layer can attribute end to end: kind, class
#: and file all derive from this source text alone.
_ATTRIBUTED_REGISTRATION_BODY = (
    "from maistro.graph.nodes import register_node\n"
    "\n"
    "\n"
    "@register_node\n"
    "class _Synthetic:\n"
    "    kind = 'x.synthetic'\n"
    "    async def _execute(self, inputs, ctx):\n"
    "        raise NotImplementedError\n"
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
    the core catalog registers the core kinds and no `creative.*`; importing
    the real design registration module is what adds them. Unrelated test
    collection order therefore cannot change what the guards prove — the
    helper performs the loading itself.

    Since #987 the design package's own import chain also registers the
    governed wave kinds, so "what loading adds" is the design package's
    production kinds as a whole — the creative ones and the wave ones."""
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
    assert not {kind for kind in bare if kind.startswith(("creative.", "design."))}
    # What loading adds is exactly what the reconciled universe attributes to
    # the design package's production registration modules.
    production_kinds = _real_reconciliation().production_kinds
    from_design = {kind for kind, module in production_kinds.items() if module == _CREATIVE_MODULE}
    from_design_package = {
        kind for kind, module in production_kinds.items() if module.startswith("maistro_design.")
    }
    assert len(from_design) == 11, sorted(from_design)
    assert added == from_design_package
    assert from_design <= added
    assert from_design_package <= {kind for kind in list_kinds() if not kind.startswith("test.")}


def test_the_loaded_registration_modules_are_importable_production_modules() -> None:
    """Every loaded identity is a real module with a real file behind it —
    the guard loads production code, not registry entries a fixture made."""
    import importlib

    for dotted in sorted(LOADED_REGISTRATION_MODULES):
        module = importlib.import_module(dotted)
        assert getattr(module, "__file__", None), dotted


# --- statically derived identity inventory (#1864) -----------------------------------


def test_the_static_inventory_covers_exactly_the_loaded_reachable_modules() -> None:
    """The identity layer and the loading layer describe the same universe:
    every statically attributed registration module is one the loader
    imported, and none of them came out empty (which would mean the extractor
    dropped references the site scan saw)."""
    assert set(_EXPECTED) == set(LOADED_REGISTRATION_MODULES)
    assert _EXPECTED, "the static inventory attributed no registration modules"
    empty = sorted(module for module, regs in _EXPECTED.items() if not regs)
    assert not empty, f"scanned registration modules with no expected registration: {empty}"


@pytest.mark.parametrize("reg", _expected_registrations(), ids=lambda reg: reg.kind)
def test_the_registry_binds_each_expected_registration_to_its_defining_identity(
    reg: ExpectedRegistration,
) -> None:
    """The four identity witnesses per registration: the kind is registered,
    to the class the source names, in the module the source ships it in,
    compiled from the checkout file the source scan attributed — so a wrong
    class, a same-named substitute or a stale module copy cannot pass."""
    cls = get_node(reg.kind)  # absent -> KeyError naming the missing kind
    assert cls.__name__ == reg.class_name
    assert cls.__module__ == reg.module
    from ._registration_inventory import _own_function_files

    witnessed = _own_function_files(cls)
    assert witnessed, "class defines no own functions; source-file parity has no witness"
    assert all(Path(name).resolve() == reg.file.resolve() for name in witnessed), (
        f"{reg.kind!r} is compiled from {sorted(witnessed)}, not the checkout file {reg.file}"
    )


def test_the_parity_report_is_clean_and_checks_the_whole_minimum() -> None:
    """The aggregate proof the fresh-process case reuses: no expected kind
    missing, none substituted, none from another source file, and the
    positive result covers the entire statically derived minimum."""
    report = verify_identity_parity(_EXPECTED)
    assert report.checked == len(_expected_registrations())
    assert not report.failures(), report.failures()


def test_incidental_extra_registrations_are_reported_separately_from_the_minimum() -> None:
    """Registry entries outside the derived reachable minimum are reported as
    data on their own — never folded into the production reachability proof
    (and today, none exist: extras would mean a registration no shipped
    source expression accounts for)."""
    report = verify_identity_parity(_EXPECTED)
    assert isinstance(report.extras, dict), "extras must be reported separately"
    assert not report.extras, (
        f"incidental extra registrations outside the reachable minimum: {report.extras}"
    )


def test_the_static_minimum_does_not_narrow_the_broader_guard_coverage() -> None:
    """The derived minimum is exactly that — a floor. The guards' broader
    non-`test.*` registry sweep keeps covering incidental entries on top of
    it, so deriving the minimum cannot shrink what the sweeps prove."""
    from .test_node_composition import shipped_kinds

    minimum = {reg.kind for reg in _expected_registrations()}
    broader = set(shipped_kinds())
    assert minimum <= broader
    assert broader - minimum == set(verify_identity_parity(_EXPECTED).extras)


# --- fresh process: a core-only load fails the proof ---------------------------------


def _pytest_pythonpath() -> list[str]:
    """The collection paths CI's core command gives its pytest processes."""
    config = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return list(tomllib.loads(config)["tool"]["pytest"]["ini_options"]["pythonpath"])


def test_a_fresh_core_only_load_fails_the_proof_for_reachable_design_registrations() -> None:
    """The #1082 selection hole, executed end to end: a fresh interpreter
    loading only the core catalog fails the identity proof for every
    reachable design registration — naming each missing kind and the design
    module that ships it — even though this parent pytest process has Design
    imported and its own registry passes. The proof reads the loader's
    attribution, not whichever imports happened to precede collection."""
    # The parent has previously imported Design through the real loaders:
    assert "maistro_design.creative_nodes" in sys.modules
    parent_creative = [kind for kind in list_kinds() if kind.startswith("creative.")]
    assert parent_creative, "parent registry lacks the creative kinds it imported"

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_REPO_ROOT / entry) for entry in _pytest_pythonpath()])
    probe = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, r'{Path(__file__).parent}')\n"
        "import maistro.graph.nodes as nodes\n"
        "registry = {k: nodes.get_node(k) for k in nodes.list_kinds()"
        " if not k.startswith('test.')}\n"
        "from _registration_inventory import (\n"
        "    expected_registrations, verify_identity_parity,\n"
        ")\n"
        f"expected = expected_registrations(Path(r'{_REPO_ROOT}'))\n"
        "report = verify_identity_parity(expected, kind_classes=registry)\n"
        "print(json.dumps({\n"
        "    'bare': sorted(registry),\n"
        "    'missing': report.missing,\n"
        "}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    observed: dict[str, Any] = json.loads(proc.stdout)

    bare = set(observed["bare"])
    assert not {kind for kind in bare if kind.startswith(("creative.", "design."))}
    missing = observed["missing"]
    creative_missing = {k: v for k, v in missing.items() if k.startswith("creative.")}
    assert len(creative_missing) == 11, sorted(creative_missing)
    assert all(source.startswith(_CREATIVE_MODULE) for source in creative_missing.values()), (
        creative_missing
    )
    reachable_design = {
        reg.kind: reg.module
        for module, regs in _EXPECTED.items()
        if module.startswith("maistro_design.")
        for reg in regs
    }
    assert set(missing) == set(reachable_design), sorted(missing)
    assert all(missing[kind].startswith(module) for kind, module in reachable_design.items()), (
        missing
    )

    # The actual production loaders pass the same proof, in this process:
    assert not verify_identity_parity(_EXPECTED).failures()


# --- parity negatives: substituted identities cannot pass ----------------------------


def test_a_wrong_registered_class_cannot_satisfy_identity_parity() -> None:
    """The registry binds the expected kind to a different class entirely:
    parity fails naming both class identities."""
    reg = _expected_for_kind("llm.summarize")
    substitute = get_node("creative.brief_resolve")
    report = verify_identity_parity(
        {reg.module: [reg]},
        kind_classes={"llm.summarize": substitute},
    )
    assert report.missing == {}
    assert report.wrong_class == {"llm.summarize": (reg.class_name, substitute.__name__)}


def test_a_same_named_substituted_class_cannot_satisfy_identity_parity() -> None:
    """A different class with the exact expected name, defined (and therefore
    compiled) elsewhere: the defining-module witness fails."""
    reg = _expected_for_kind("llm.summarize")

    # Same name, wrong provenance: defined in this test module.
    class LlmSummarizeNode:
        pass

    report = verify_identity_parity(
        {reg.module: [reg]},
        kind_classes={"llm.summarize": LlmSummarizeNode},
    )
    assert report.wrong_class == {}
    assert report.wrong_module == {"llm.summarize": (reg.module, LlmSummarizeNode.__module__)}
    assert report.wrong_source_file, "a substitute class must also fail file parity"


def test_a_wrong_source_file_module_cannot_satisfy_identity_parity() -> None:
    """A same-named class whose `__module__` is spoofed to the expected
    module passes the name and module witnesses, but its own methods still
    compile from wherever it was really defined — the code-object witness
    pins the checkout file."""
    reg = _expected_for_kind("llm.summarize")

    class LlmSummarizeNode:
        async def _execute(self, inputs: object, ctx: object) -> object:
            raise NotImplementedError

    LlmSummarizeNode.__module__ = reg.module  # spoofed binding
    compiled_from = [
        value.__code__.co_filename
        for value in vars(LlmSummarizeNode).values()
        if hasattr(value, "__code__")
    ]
    assert compiled_from and all(
        Path(name).resolve() != reg.file.resolve() for name in compiled_from
    )
    report = verify_identity_parity(
        {reg.module: [reg]},
        kind_classes={"llm.summarize": LlmSummarizeNode},
    )
    assert report.wrong_class == {} and report.wrong_module == {}
    assert report.wrong_source_file == {
        "llm.summarize": (str(reg.file), sorted(set(compiled_from)))
    }


def test_a_missing_reachable_registration_fails_naming_kind_and_source() -> None:
    """A reachable source registration the loader's registry never received
    fails with the missing kind AND its shipping module/file identified — no
    hand-maintained list is consulted anywhere in the detection."""
    reg = _expected_for_kind("llm.summarize")
    report = verify_identity_parity({reg.module: [reg]}, kind_classes={})
    assert report.missing == {"llm.summarize": reg.source}
    assert "llm.summarize" in report.failures()[0]


def test_a_new_reachable_source_registration_needs_no_hand_maintained_list(
    tmp_path: Path,
) -> None:
    """The audit's prospective case, on a synthetic tree: adding a reachable
    registration file makes the static inventory derive its kind, class and
    file from source alone — so a registry without it fails naming all
    three, without any census update."""
    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": _ATTRIBUTED_REGISTRATION_BODY},
        unreachable=set(),
        dispositioned=set(),
    )

    derived = expected_registrations(root)
    assert set(derived) == {"x.reg"}
    (reg,) = derived["x.reg"]
    assert (reg.kind, reg.class_name, reg.module) == ("x.synthetic", "_Synthetic", "x.reg")
    assert reg.file == root / "packages" / "x" / "src" / "x" / "reg.py"

    report = verify_identity_parity(derived, kind_classes={})
    assert report.missing == {"x.synthetic": reg.source}


def test_a_ledgered_unreachable_registration_is_out_of_the_expected_minimum(
    tmp_path: Path,
) -> None:
    """A registration module the reachability ledger classifies unreachable
    (with the reconciliation's reviewed disposition) never loads, so the
    static inventory excludes it too — the same identities, or the module-set
    equality and registry parity would demand kinds production never runs.
    """
    root = _synthetic_repo(
        tmp_path,
        registration_files={
            "packages/x/src/x/reg.py": _ATTRIBUTED_REGISTRATION_BODY,
            "packages/x/src/x/shelved.py": _REGISTRATION_BODY,
        },
        unreachable={"x.shelved"},
        dispositioned={"x.shelved"},
    )

    derived = expected_registrations(root)
    assert set(derived) == {"x.reg"}, (
        "a ledgered-unreachable registration site leaked into the expected "
        "minimum the loading layer is compared against"
    )


def test_a_registrar_call_inside_another_statement_call_is_diagnosed(
    tmp_path: Path,
) -> None:
    """A registration hidden in the arguments of an unrelated statement call
    (`consume(register_node(A))`) is diagnosed, not dropped: a scan that
    never traverses those arguments leaves the module out of the universe
    entirely, silently omitting a reachable registration site from every
    downstream proof instead of failing closed.
    """
    root = _synthetic_repo(
        tmp_path,
        registration_files={
            "packages/x/src/x/reg.py": (
                "from maistro.graph.nodes import register_node\n"
                "\n"
                "\n"
                "class Wrapped:\n"
                "    kind = 'x.wrapped'\n"
                "\n"
                "\n"
                "consume(register_node(Wrapped))\n"
            )
        },
        unreachable=set(),
        dispositioned=set(),
    )
    assert set(scan_registration_modules(root)) == {"x.reg"}, (
        "a module whose registrar call hides inside another call must still "
        "enter the universe — skipping it silently hides a registration site"
    )
    with pytest.raises(UnsupportedRegistration, match="x\\.reg"):
        expected_registrations(root)


# --- static extraction: shipped forms attribute exactly ------------------------------


def _inventory_of(tmp_path: Path, body: str, dotted: str = "x.reg") -> list[ExpectedRegistration]:
    path = tmp_path / "reg.py"
    path.write_text(body, encoding="utf-8")
    return expected_in_module(path, dotted)


def _two_class_body(import_line: str) -> str:
    return (
        f"{import_line}\n"
        "\n"
        "\n"
        "class Alpha:\n"
        "    kind = 'x.alpha'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    kind: ClassVar[str] = 'x.beta'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
    )


def test_a_decorator_registration_attributes_its_class(tmp_path: Path) -> None:
    regs = _inventory_of(
        tmp_path,
        _two_class_body("from maistro.graph.nodes import register_node")
        + "\n\n@register_node\nclass Decorated:\n"
        "    kind = 'x.decorated'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n",
    )
    assert [(r.class_name, r.kind) for r in regs] == [("Decorated", "x.decorated")]
    assert regs[0].line > 0 and regs[0].module == "x.reg"
    assert regs[0].file == tmp_path / "reg.py"


def test_a_relative_import_decorator_attributes_its_class(tmp_path: Path) -> None:
    """The core leaf modules' shipped form: `from . import register_node`.
    The dotted name must place the module inside maistro.graph.nodes for the
    relative import to resolve to the registrar."""
    body = (
        "from __future__ import annotations\n"
        "from . import register_node\n"
        "\n"
        "\n"
        "@register_node\n"
        "class Relative:\n"
        "    kind = 'x.relative'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
    )
    regs = _inventory_of(tmp_path, body, dotted="maistro.graph.nodes.relative_kind")
    assert [(r.class_name, r.kind, r.module) for r in regs] == [
        ("Relative", "x.relative", "maistro.graph.nodes.relative_kind")
    ]


def test_an_aliased_registrar_import_enters_the_universe(tmp_path: Path) -> None:
    """`import register_node as rn` then `rn(Cls)`: the site scan must see the
    module (a name-literal-only scan silently missed it — a deceptively
    smaller universe) and the extraction must attribute the call."""
    body = (
        "from maistro.graph.nodes import register_node as rn\n"
        "\n"
        "\n"
        "class Aliased:\n"
        "    kind = 'x.aliased'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "rn(Aliased)\n"
    )
    assert [(r.class_name, r.kind) for r in _inventory_of(tmp_path, body)] == [
        ("Aliased", "x.aliased")
    ]

    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": body},
        unreachable=set(),
        dispositioned=set(),
    )
    assert set(scan_registration_modules(root)) == {"x.reg"}


def test_literal_loops_and_module_constants_attribute_each_class(tmp_path: Path) -> None:
    """The creative_nodes shipped form (inline tuple loop) plus its accepted
    variants (module-constant iterable, module-constant kind): every class
    gets its own correct identity, and unrelated loops do not conflate."""
    body = (
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "_FIRST_KIND = 'x.first'\n"
        "\n"
        "\n"
        "class First:\n"
        "    kind = _FIRST_KIND\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "class Second:\n"
        "    kind = 'x.second'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "class Third:\n"
        "    kind = 'x.third'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "for _node_cls in (First, Second):\n"
        "    register_node(_node_cls)\n"
        "\n"
        "\n"
        "_LAST = (Third,)\n"
        "for _other_cls in _LAST:\n"
        "    register_node(_other_cls)\n"
    )
    regs = _inventory_of(tmp_path, body)
    assert [(r.class_name, r.kind) for r in regs] == [
        ("First", "x.first"),
        ("Second", "x.second"),
        ("Third", "x.third"),
    ]


def test_a_direct_call_and_a_loop_in_one_module_stay_separate(tmp_path: Path) -> None:
    body = (
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "\n"
        "class Solo:\n"
        "    kind = 'x.solo'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "class Paired:\n"
        "    kind = 'x.paired'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "register_node(Solo)\n"
        "for _cls in (Paired,):\n"
        "    register_node(_cls)\n"
    )
    regs = _inventory_of(tmp_path, body)
    assert [(r.class_name, r.kind) for r in regs] == [
        ("Solo", "x.solo"),
        ("Paired", "x.paired"),
    ]


def test_unrelated_loops_reusing_a_target_name_stay_unambiguous(
    tmp_path: Path,
) -> None:
    """Two module-level loops that share a target name but bind no registrar
    call are not a registration ambiguity: rejecting them would make any
    valid initialization code with repeated loop targets fail inventory
    construction, while only loops whose bindings participate in a
    registration can conflate one.
    """
    body = (
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "\n"
        "@register_node\n"
        "class Solo:\n"
        "    kind = 'x.solo'\n"
        "\n"
        "\n"
        "for item in (1, 2):\n"
        "    pass\n"
        "for item in (3, 4):\n"
        "    pass\n"
    )
    assert [(r.class_name, r.kind) for r in _inventory_of(tmp_path, body)] == [("Solo", "x.solo")]


def test_a_module_level_match_statement_registers_at_module_scope(
    tmp_path: Path,
) -> None:
    """A module-level `match` is import-time code: its case bodies stay at
    module scope, so a registration inside one is attributed exactly like a
    direct call. A scanner that never traversed match statements would leave
    the whole module out of the universe (the site scan would see no registrar
    reference at all), silently omitting a reachable registration site from
    every downstream proof instead of proving it."""
    body = (
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "_SHIPPED = True\n"
        "\n"
        "\n"
        "class Matched:\n"
        "    kind = 'x.matched'\n"
        "    async def _execute(self, inputs, ctx):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "match _SHIPPED:\n"
        "    case True:\n"
        "        register_node(Matched)\n"
        "    case _:\n"
        "        pass\n"
    )
    assert [(r.class_name, r.kind) for r in _inventory_of(tmp_path, body)] == [
        ("Matched", "x.matched")
    ]

    root = _synthetic_repo(
        tmp_path,
        registration_files={"packages/x/src/x/reg.py": body},
        unreachable=set(),
        dispositioned=set(),
    )
    assert set(scan_registration_modules(root)) == {"x.reg"}, (
        "a module whose only registrar call sits in a match case must still "
        "enter the universe — skipping match statements hides the whole site"
    )


# --- static extraction: unsupported forms fail closed --------------------------------


def _assert_unsupported(tmp_path: Path, body: str, diagnosis: str, dotted: str = "x.reg") -> None:
    path = tmp_path / "reg.py"
    path.write_text(body, encoding="utf-8")
    try:
        expected_in_module(path, dotted)
    except UnsupportedRegistration as exc:
        assert diagnosis in str(exc), str(exc)
        assert dotted in str(exc), f"diagnosis must name the module: {exc}"
    else:  # pragma: no cover - the failure is the point
        raise AssertionError(f"expected UnsupportedRegistration for: {diagnosis}")


def test_dynamic_registration_arguments_fail_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "def build():\n"
        "    return object\n"
        "\n"
        "register_node(build())\n",
        "dynamic registration argument",
    )


def test_qualified_registrar_access_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "import maistro.graph.nodes as g\n"
        "\n"
        "\n"
        "class Qualified:\n"
        "    kind = 'x.qualified'\n"
        "\n"
        "g.register_node(Qualified)\n",
        "qualified registrar access",
    )


def test_star_import_registrar_access_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import *\n"
        "\n"
        "\n"
        "class Starred:\n"
        "    kind = 'x.starred'\n"
        "\n"
        "register_node(Starred)\n",
        "unclassified registrar reference",
    )


def test_a_reexport_chain_registrar_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from .shim import register_node\n"
        "\n"
        "\n"
        "class Reexported:\n"
        "    kind = 'x.reexported'\n"
        "\n"
        "register_node(Reexported)\n",
        "unclassified registrar reference",
    )


def test_nested_deferred_registration_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "\n"
        "class Deferred:\n"
        "    kind = 'x.deferred'\n"
        "\n"
        "\n"
        "def setup() -> None:\n"
        "    register_node(Deferred)\n",
        "nested inside a function/class body",
    )


def test_ambiguous_loop_bindings_fail_closed(tmp_path: Path) -> None:
    body = _two_class_body("from maistro.graph.nodes import register_node")
    _assert_unsupported(
        tmp_path,
        body + "\n\nfor _cls in (Alpha,):\n    register_node(_cls)\n"
        "for _cls in (Beta,):\n    register_node(_cls)\n",
        "ambiguous loop bindings",
    )


def test_a_stray_call_referencing_a_leaked_loop_variable_fails_closed(
    tmp_path: Path,
) -> None:
    """A module-level call after the loop references the loop variable's
    leaked binding — not attributable to any literal sequence, so it fails
    closed instead of silently re-registering whatever the loop last held."""
    body = _two_class_body("from maistro.graph.nodes import register_node")
    _assert_unsupported(
        tmp_path,
        body + "\n\nfor _cls in (Alpha,):\n    register_node(_cls)\nregister_node(_cls)\n",
        "dynamic registration sequence",
    )


def test_a_loop_call_not_passing_the_target_fails_closed(tmp_path: Path) -> None:
    body = _two_class_body("from maistro.graph.nodes import register_node")
    _assert_unsupported(
        tmp_path,
        body + "\n\nfor _cls in (Alpha,):\n    register_node(Alpha)\n",
        "does not pass exactly the loop target",
    )


def test_a_loop_target_shadowing_a_module_name_fails_closed(tmp_path: Path) -> None:
    """A single registration loop whose target shadows a module-level
    constant or class fails closed exactly like a repeated target: attribution
    must not depend on guessing which binding a shadowed name denotes, so the
    binding has to be renamed before the inventory attributes the loop."""
    body = _two_class_body("from maistro.graph.nodes import register_node")
    _assert_unsupported(
        tmp_path,
        body
        + "\n\n_ALPHA_KIND = 'x.alpha'\nfor _ALPHA_KIND in (Beta,):\n    register_node(_ALPHA_KIND)\n",
        "ambiguous loop bindings",
    )
    _assert_unsupported(
        tmp_path,
        body + "\n\nfor Alpha in (Beta,):\n    register_node(Alpha)\n",
        "ambiguous loop bindings",
    )


def test_a_non_literal_kind_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "def compute_kind():\n"
        "    return 'x.computed'\n"
        "\n"
        "\n"
        "@register_node\n"
        "class Computed:\n"
        "    kind = compute_kind()\n",
        "has no `kind` this inventory can resolve",
    )


def test_a_missing_kind_fails_closed(tmp_path: Path) -> None:
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "\n"
        "@register_node\n"
        "class Kindless:\n"
        "    pass\n",
        "has no `kind` this inventory can resolve",
    )


def test_a_dynamic_loop_iterable_fails_closed(tmp_path: Path) -> None:
    body = _two_class_body("from maistro.graph.nodes import register_node")
    _assert_unsupported(
        tmp_path,
        body + "\n\ndef candidates():\n    return (Alpha,)\n"
        "\nfor _cls in candidates():\n    register_node(_cls)\n",
        "dynamic registration sequence",
    )


def test_a_registrar_call_in_a_match_header_fails_closed(tmp_path: Path) -> None:
    """The match subject is evaluated at import time but is not a
    statement-position registration call: a registrar reference there is
    deferred, so it is diagnosed rather than silently dropped. A scanner that
    never looked inside match statements would omit the whole module from the
    universe instead of failing closed on the reference it cannot attribute."""
    _assert_unsupported(
        tmp_path,
        "from maistro.graph.nodes import register_node\n"
        "\n"
        "\n"
        "class Guarded:\n"
        "    kind = 'x.guarded'\n"
        "\n"
        "\n"
        "match register_node(Guarded):\n"
        "    case _:\n"
        "        pass\n",
        "deferred registration",
    )

"""RSI stays non-production-reachable until #552's M5 containment gates.

Issue #1138 lands the Warden harvest boundary as safety work on an *operator*
surface. Its acceptance criteria require that landing the leaf cannot change
RSI's activation defaults, and that RSI remains disabled outside explicitly
invoked operator tooling until #552's M5 containment gates are satisfied.

What "disabled" concretely means in this repository, and what these tests pin:

- No engine product package (server, core, canvas, turing, design, bootstrap,
  registry) imports ``maistro_rsi`` at all, statically or dynamically. ADR
  081226-034b keeps RSI a specialized package; the engine products that ship
  must not be able to reach it without this file failing first.
- The one product surface that does reference RSI is the Conductor app, which
  treats maistro-rsi as an optional dependency confined to its services and
  routes. Its single HTTP-reachable run path is gated on a real containment
  attestation: ``IN_PROCESS_ISOLATION_AVAILABLE`` defaults to ``None`` (a
  gate, not a constant — see ``rsi_execution_policy.py``) and is answered by
  the container dispatch backend's probe, and ``POST /v1/rsi/runs`` resolves
  that gate through ``require_isolation()`` before dispatching anything. A
  bare ``True`` or ``False`` constant there would be the check silenced —
  attesting containment nobody verified, or refusing runs the backend can
  actually contain.

Flip the flag, drop the call, or wire RSI into an engine package, and these
tests fail. The scanner-sensitivity cases build the offending trees in
``tmp_path`` so a green run is proven to be a real scan, not a vacuous one.

These are static on purpose: the maistro-rsi suite must be able to prove the
activation invariant without importing the Conductor app (a flat layout with
its own settings machinery) or booting a server.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]

#: Engine product packages that ship. RSI must not be reachable from any of
#: them; the Conductor app (hive-conductor) is the single deliberate, gated
#: exception tracked by its own execution policy (#305/#509/#552).
ENGINE_PACKAGE_ROOTS = tuple(
    ROOT / "packages" / package / "src"
    for package in (
        "maistro-server",
        "maistro-core",
        "maistro-canvas",
        "maistro-turing",
        "maistro-design",
        "maistro-bootstrap",
        "maistro-registry",
    )
)

CONDUCTOR_PRODUCT_ROOTS = (
    ROOT / "packages" / "hive-conductor" / "backend" / "services",
    ROOT / "packages" / "hive-conductor" / "backend" / "routes",
)
EXECUTION_POLICY = (
    ROOT / "packages" / "hive-conductor" / "backend" / "services" / "rsi_execution_policy.py"
)
RUN_ROUTE = ROOT / "packages" / "hive-conductor" / "backend" / "routes" / "rsi.py"

#: The complete, deliberate set of product (non-test) files allowed to reach
#: the RSI package. Anything else appearing here is new wiring this test was
#: written to stop: an engine package growing an import, or a new Conductor
#: module reaching around the execution policy. Updating this set is a
#: #552-gated decision, not a test fix.
CONFINED_RSI_PRODUCT_SURFACES = frozenset(
    {
        "packages/hive-conductor/backend/services/rsi.py",
        "packages/hive-conductor/backend/routes/rsi.py",
    }
)

_DYNAMIC_IMPORT_FUNCS = frozenset({"import_module", "__import__"})


def _names_rsi(name: str) -> bool:
    return name == "maistro_rsi" or name.startswith("maistro_rsi.")


def module_imports_rsi(tree: ast.Module) -> bool:
    """Whether a parsed module reaches the maistro_rsi package.

    Static ``import``/``from`` statements and the two dynamic-import call
    forms with a constant module argument. That combination is what the
    Conductor's optional-dependency seam itself uses
    (``import maistro_rsi`` inside ``_rsi_available``), so the scan sees the
    one legitimate pattern rather than assuming imports are only spelled one
    way.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(_names_rsi(alias.name) for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and _names_rsi(node.module or ""):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _DYNAMIC_IMPORT_FUNCS and node.args:
                argument = node.args[0]
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and _names_rsi(argument.value)
                ):
                    return True
    return False


def rsi_importers(roots: tuple[Path, ...]) -> list[Path]:
    """Every Python file under ``roots`` whose module imports maistro_rsi."""
    offenders: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if module_imports_rsi(tree):
                offenders.append(path)
    return offenders


def _module_constant(tree: ast.Module, name: str) -> Any:
    """The value of a module-level ``name = <constant>`` assignment, if any."""
    for node in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            target = getattr(node, "target", None)
            targets, value = ([target] if target is not None else []), getattr(node, "value", None)
        else:
            continue
        if isinstance(value, ast.Constant) and any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            return value.value
    return None


def hardcoded_isolation_flag(path: Path) -> bool | None:
    """The isolation flag's value *when it is a bare bool*, else ``None``.

    Parsed, not string-matched. The shipped gate must be ``None`` — the answer
    comes from the dispatch backend's probe (#509). A bare ``True`` attests
    containment nobody verified (the silenced check); a bare ``False`` is
    #305's refuse-everything constant, which #509 replaced with a working
    path. Either constant is returned here so the pin can flag it; anything
    else — a missing assignment or a non-bool — reads as *not* a bare bool and
    is reported as ``None`` by the type, which the pin's assertion on the real
    file distinguishes from a genuine ``None`` default.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _module_constant(tree, "IN_PROCESS_ISOLATION_AVAILABLE")
    return value if isinstance(value, bool) else None


def route_requires_isolation(path: Path, function_name: str = "start_run") -> bool:
    """Whether a route module's ``function_name`` calls ``require_isolation``.

    The disabled flag only stops an HTTP run if the run path actually resolves
    it. Scanning just the function body keeps the pin honest: a call elsewhere
    in the module does not gate this route.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        ):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "require_isolation":
                return True
    return False


@pytest.mark.ac("SPEC-092526-c41d/AC-8")
@pytest.mark.contract("boundary")
def test_no_engine_product_package_imports_the_rsi_surface() -> None:
    """The shipped engine products cannot reach maistro_rsi at all.

    If any of them grows an import, RSI has been wired into a production
    surface without the M5 containment conversation #552 owns — and this file
    is where that must fail.
    """
    assert rsi_importers(ENGINE_PACKAGE_ROOTS) == []


@pytest.mark.ac("SPEC-092526-c41d/AC-8")
def test_product_rsi_references_stay_confined_to_the_policy_gated_conductor() -> None:
    """Every product file that reaches RSI is one of the two known gated seams.

    The Conductor's run path is the only deliberate product exposure, and it
    is held by the execution policy the next test pins. A file outside this
    set appearing here is new activation wiring, whatever it calls itself.
    """
    importers = {
        path.relative_to(ROOT).as_posix()
        for path in rsi_importers((*ENGINE_PACKAGE_ROOTS, *CONDUCTOR_PRODUCT_ROOTS))
    }
    assert importers == CONFINED_RSI_PRODUCT_SURFACES


@pytest.mark.ac("SPEC-092526-c41d/AC-8")
def test_the_http_run_gate_attests_a_real_backend_not_a_constant() -> None:
    """``POST /v1/rsi/runs`` is gated on containment that is actually probed.

    Two halves, both load-bearing: the isolation flag's module default is not
    a bare bool (a ``True`` would attest containment nobody verified; a
    ``False`` would be #305's refusal that #509 replaced with a working path —
    the shipped answer must come from the dispatch backend's probe), and the
    run route resolves that gate before dispatching. Either half regressing
    re-opens the HTTP activation path this acceptance criterion forbids.
    """
    assert hardcoded_isolation_flag(EXECUTION_POLICY) is None
    assert route_requires_isolation(RUN_ROUTE)


@pytest.mark.ac("SPEC-092526-c41d/AC-9")
@pytest.mark.parametrize(
    ("source", "reaches_rsi"),
    [
        ("import maistro_rsi", True),
        ("import maistro_rsi.local_loop as local_loop", True),
        ("from maistro_rsi.local_loop import LocalRsiLoop", True),
        ("importlib.import_module('maistro_rsi.runner')", True),
        ("__import__('maistro_rsi.gateway')", True),
        # Neighbouring packages must not trip the scan, or it proves nothing.
        ("import maistro_evolve", False),
        ("from maistro_evolve.types import EvalResult", False),
        ("importlib.import_module('maistro.core')", False),
        # Docstring/comment mentions are references, not reachability.
        ('"""maistro_rsi.gateway is described here."""', False),
    ],
)
def test_the_import_scanner_flags_every_way_to_reach_rsi(
    tmp_path: Path, source: str, reaches_rsi: bool
) -> None:
    """The confinement scan sees each import form and ignores mere mentions."""
    module = tmp_path / "product_module.py"
    module.write_text(source, encoding="utf-8")

    tree = ast.parse(module.read_text(encoding="utf-8"))
    assert module_imports_rsi(tree) is reaches_rsi


@pytest.mark.ac("SPEC-092526-c41d/AC-9")
def test_the_activation_pins_flag_the_violations_they_exist_to_catch(
    tmp_path: Path,
) -> None:
    """A hardcoded isolation default or a dropped route call fails loudly."""
    enabled = tmp_path / "enabled_policy.py"
    enabled.write_text("IN_PROCESS_ISOLATION_AVAILABLE: Final = True\n", encoding="utf-8")
    assert hardcoded_isolation_flag(enabled) is True

    refused = tmp_path / "refused_policy.py"
    refused.write_text("IN_PROCESS_ISOLATION_AVAILABLE: Final = False\n", encoding="utf-8")
    assert hardcoded_isolation_flag(refused) is False

    gated = tmp_path / "gated_policy.py"
    gated.write_text("IN_PROCESS_ISOLATION_AVAILABLE: bool | None = None\n", encoding="utf-8")
    assert hardcoded_isolation_flag(gated) is None

    unguarded = tmp_path / "unguarded_route.py"
    unguarded.write_text(
        "async def start_run(body):\n"
        "    return {'run_id': 'r-1'}\n"
        "\n"
        "def stop_run(run_id):\n"
        "    rsi_execution_policy.require_isolation()\n",
        encoding="utf-8",
    )
    # A require_isolation call outside start_run does not gate the run route.
    assert not route_requires_isolation(unguarded)

    guarded = tmp_path / "guarded_route.py"
    guarded.write_text(
        "async def start_run(body):\n"
        "    isolation = rsi_execution_policy.require_isolation()\n"
        "    return {'isolation': isolation}\n",
        encoding="utf-8",
    )
    assert route_requires_isolation(guarded)

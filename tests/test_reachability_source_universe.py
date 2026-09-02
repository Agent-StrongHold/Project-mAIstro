from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-reachability.py"
SPEC = importlib.util.spec_from_file_location("check_reachability_source_universe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
reachability = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reachability
SPEC.loader.exec_module(reachability)


def _write_frontend_server(root: Path) -> Path:
    server = root / "packages" / "demo" / "frontend" / "server"
    server.mkdir(parents=True)
    (server / "main.py").write_text("from services import worker\n")
    (server / "services").mkdir()
    (server / "services" / "__init__.py").write_text("")
    (server / "services" / "worker.py").write_text("VALUE = 1\n")
    (server / "dead.py").write_text("VALUE = 2\n")
    return server


def test_undeclared_frontend_server_fails_closed_instead_of_escaping_analysis(
    tmp_path: Path,
) -> None:
    _write_frontend_server(tmp_path)

    with pytest.raises(RuntimeError, match="outside reachability analysis"):
        reachability._collect_modules(tmp_path, ())


def test_declared_frontend_server_participates_in_the_flat_app_graph(tmp_path: Path) -> None:
    _write_frontend_server(tmp_path)
    app = reachability.FlatApp(
        name="demo-frontend-server",
        path="packages/demo/frontend/server",
        roots=("main",),
        report_prefix="demo-frontend-server",
    )

    mods, seen = reachability._reachability(
        root=tmp_path,
        flat_apps=(app,),
        static_roots=(),
        dynamic_roots=(),
    )

    main = reachability._flat_key(app.name, "main")
    worker = reachability._flat_key(app.name, "services.worker")
    dead = reachability._flat_key(app.name, "dead")

    assert {main, worker, dead} <= set(mods)
    assert {main, worker} <= seen
    assert dead not in seen


def test_a_classified_file_inside_a_declared_app_is_not_a_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_frontend_server(tmp_path)
    (tmp_path / "packages" / "demo" / "frontend" / "server" / "legacy.py").write_text("X = 1\n")
    monkeypatch.setattr(
        reachability,
        "_EXCLUDED_PACKAGE_PYTHON",
        frozenset({"packages/demo/frontend/server/legacy.py"}),
    )
    app = reachability.FlatApp(
        name="demo-frontend-server",
        path="packages/demo/frontend/server",
        roots=("main",),
    )

    mods, _seen = reachability._reachability(
        root=tmp_path, flat_apps=(app,), static_roots=(), dynamic_roots=()
    )

    legacy = reachability._flat_key(app.name, "legacy")
    dead = reachability._flat_key(app.name, "dead")
    # The classification removes the module from the graph entirely; it is not
    # an unreachable entry that would have to be banked in the baseline.
    assert legacy not in mods
    # Everything not classified still fails closed into the unreachable set.
    assert dead in mods


def test_an_immutable_vendored_tree_is_classified_not_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendored = tmp_path / "packages" / "demo" / "vendored"
    vendored.mkdir(parents=True)
    (vendored / "tool.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(
        reachability, "_IMMUTABLE_VENDORED_TREES", frozenset({"packages/demo/vendored"})
    )

    mods = reachability._collect_modules(tmp_path, ())

    assert not [key for key, path in mods.items() if "vendored" in path.parts]

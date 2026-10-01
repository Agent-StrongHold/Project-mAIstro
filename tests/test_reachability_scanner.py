from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-reachability.py"
SPEC = importlib.util.spec_from_file_location("check_reachability", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
reachability = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reachability
SPEC.loader.exec_module(reachability)


def _flat(app: str, module: str) -> str:
    return reachability._flat_key(app, module)


def test_turing_backend_modules_are_collected_and_reachable_from_real_entrypoint() -> None:
    mods, seen = reachability._reachability()

    assert _flat("maistro-turing-backend", "main") in mods
    assert _flat("maistro-turing-backend", "main") in seen
    assert _flat("maistro-turing-backend", "config") in seen
    assert _flat("maistro-turing-backend", "middleware.auth") in seen
    assert _flat("maistro-turing-backend", "routes.health") in seen


def test_hive_and_turing_flat_namespaces_do_not_collide() -> None:
    mods, seen = reachability._reachability()

    hive_main = _flat("hive-conductor", "main")
    turing_main = _flat("maistro-turing-backend", "main")
    hive_health = _flat("hive-conductor", "routes.health")
    turing_health = _flat("maistro-turing-backend", "routes.health")

    assert {hive_main, turing_main, hive_health, turing_health} <= set(mods)
    assert {hive_main, turing_main, hive_health, turing_health} <= seen
    assert mods[hive_main] != mods[turing_main]
    assert mods[hive_health] != mods[turing_health]


def test_flat_app_fixture_keeps_disconnected_module_unreachable(tmp_path: Path) -> None:
    backend = tmp_path / "packages" / "example" / "backend"
    (backend / "services").mkdir(parents=True)
    (backend / "tests").mkdir()
    (backend / "main.py").write_text("from services import live\n")
    (backend / "services" / "__init__.py").write_text("")
    (backend / "services" / "live.py").write_text("VALUE = 1\n")
    (backend / "dead.py").write_text("VALUE = 2\n")
    (backend / "tests" / "test_noise.py").write_text("import dead\n")

    app = reachability.FlatApp(
        name="example",
        path="packages/example/backend",
        roots=("main",),
        report_prefix="example-backend",
    )
    mods, seen = reachability._reachability(
        root=tmp_path,
        flat_apps=(app,),
        static_roots=(),
        dynamic_roots=(),
    )
    unreachable, total = reachability.unreachable_modules(
        root=tmp_path,
        flat_apps=(app,),
        static_roots=(),
        dynamic_roots=(),
    )

    assert total == 4
    assert _flat("example", "main") in seen
    assert _flat("example", "services") in seen
    assert _flat("example", "services.live") in seen
    assert unreachable == [_flat("example", "dead")]
    assert all("tests" not in path.parts for path in mods.values())


def test_undeclared_flat_backend_fails_instead_of_silently_escaping_analysis(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "packages" / "surprise" / "backend"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text("VALUE = 1\n")

    with pytest.raises(RuntimeError, match="outside reachability analysis"):
        reachability._collect_modules(tmp_path, ())

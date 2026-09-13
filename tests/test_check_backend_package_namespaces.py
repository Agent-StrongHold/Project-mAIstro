from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-backend-package-namespaces.py"


def _load_check():
    spec = importlib.util.spec_from_file_location("check_backend_package_namespaces", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backend_tree(tmp_path: Path, package: str = "hive_conductor") -> Path:
    backend = tmp_path / "packages" / "hive-conductor" / "backend"
    package_root = backend / package
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("\n", encoding="utf-8")
    return backend


def test_repository_backend_apps_use_approved_namespaces() -> None:
    check = _load_check()

    assert check.violations() == []


def test_flat_backend_module_is_rejected(tmp_path: Path) -> None:
    check = _load_check()
    backend = _backend_tree(tmp_path)
    (backend / "main.py").write_text("app = object()\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any("main.py is a flat backend module" in error for error in errors)


def test_python_outside_package_is_rejected(tmp_path: Path) -> None:
    check = _load_check()
    backend = _backend_tree(tmp_path)
    (backend / "routes").mkdir()
    (backend / "routes" / "health.py").write_text("\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any("routes contains Python outside" in error for error in errors)


def test_unknown_backend_namespace_is_rejected(tmp_path: Path) -> None:
    check = _load_check()
    backend = tmp_path / "packages" / "new-backend" / "backend"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text("app = object()\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any("has no approved application package" in error for error in errors)

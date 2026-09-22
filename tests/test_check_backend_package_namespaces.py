from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


def test_backend_root_package_init_is_rejected(tmp_path: Path) -> None:
    """A ``backend/__init__.py`` re-creates the flat collision surface.

    With the directory itself a package, any sibling module resolves as
    ``backend.<module>`` via sys.path order — the exact aliasing #1134 removed.
    """
    check = _load_check()
    backend = _backend_tree(tmp_path)
    (backend / "__init__.py").write_text("\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any(
        "makes the backend directory itself an importable package" in error for error in errors
    )


def test_unknown_backend_namespace_is_rejected(tmp_path: Path) -> None:
    check = _load_check()
    backend = tmp_path / "packages" / "new-backend" / "backend"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text("app = object()\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any("has no approved application package" in error for error in errors)


def test_package_root_without_init_is_rejected(tmp_path: Path) -> None:
    """The approved package directory must itself be a package."""
    check = _load_check()
    backend = _backend_tree(tmp_path)
    (backend / "hive_conductor" / "__init__.py").unlink()

    errors = check.violations(tmp_path)

    assert any("must contain __init__.py" in error for error in errors)


def test_python_inside_the_package_but_outside_a_subpackage_is_rejected(
    tmp_path: Path,
) -> None:
    """A bare directory inside the package is not importable either."""
    check = _load_check()
    backend = _backend_tree(tmp_path)
    nested = backend / "hive_conductor" / "routes"
    nested.mkdir()
    (nested / "chat.py").write_text("\n", encoding="utf-8")

    errors = check.violations(tmp_path)

    assert any("is not inside an __init__.py package" in error for error in errors)


def test_main_reports_violations_and_fails(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    check = _load_check()
    monkeypatch.setattr(check, "violations", lambda root=None: ["synthetic violation"])
    monkeypatch.setattr("sys.argv", ["check-backend-package-namespaces.py"])

    code = check.main()

    out = capsys.readouterr().out
    assert code == 1
    assert "backend package namespace check failed" in out
    assert "- synthetic violation" in out


def test_script_entry_point_passes_on_a_clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running the file as ``python scripts/check-backend-package-namespaces.py``
    (the CI invocation) executes ``main`` through the ``__main__`` guard and
    exits 0 on the committed tree."""
    monkeypatch.setattr("sys.argv", ["check-backend-package-namespaces.py"])
    spec = importlib.util.spec_from_file_location("__main__", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)

    with pytest.raises(SystemExit) as exc:
        spec.loader.exec_module(module)

    assert exc.value.code == 0

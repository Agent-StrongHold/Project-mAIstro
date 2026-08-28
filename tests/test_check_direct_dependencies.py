from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture()
def gate():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_direct_dependencies.py"
    spec = importlib.util.spec_from_file_location("check_direct_dependencies", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_package(tmp_path: Path, dependencies: list[str], source: str = "") -> Path:
    package = tmp_path / "packages" / "demo"
    source_dir = package / "src" / "demo"
    source_dir.mkdir(parents=True)
    deps = ",\n".join(f'    "{dependency}"' for dependency in dependencies)
    (package / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        f"{deps}\n"
        "]\n"
    )
    (source_dir / "app.py").write_text(source)
    return package


def test_requirement_name_handles_extras_and_normalization(gate) -> None:
    assert gate.requirement_name("SQLAlchemy[asyncio]>=2") == "sqlalchemy"
    assert gate.requirement_name("pydantic_settings >= 2") == "pydantic-settings"


def test_imports_from_source_collects_static_and_literal_dynamic_imports(gate) -> None:
    source = """
import httpx as client
from pydantic_settings import BaseSettings
import importlib
importlib.import_module("yaml.loader")
__import__("sqlalchemy.ext.asyncio")
"""
    assert gate.imports_from_source(source) == frozenset(
        {"httpx", "pydantic_settings", "importlib", "yaml", "sqlalchemy"}
    )


def test_production_imports_do_not_credit_test_only_usage(gate, tmp_path) -> None:
    package = _write_package(tmp_path, ["httpx"], "pass\n")
    tests = package / "tests"
    tests.mkdir()
    (tests / "test_http.py").write_text("import httpx\n")
    assert "httpx" not in gate.production_imports(package)


def test_discover_uses_distribution_to_import_mapping(gate, tmp_path) -> None:
    _write_package(tmp_path, ["PyYAML>=6"], "import yaml\n")
    usages = gate.discover(tmp_path, {"pyyaml": frozenset({"yaml"})})
    assert len(usages) == 1
    assert usages[0].unused == frozenset()


def test_missing_exception_for_unused_runtime_dependency_fails(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    failures = gate.audit([usage], {})
    assert any("uvicorn is a direct runtime dependency" in failure for failure in failures)


def test_reviewed_non_import_runtime_exception_passes(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    exceptions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    assert gate.audit([usage], exceptions) == []


def test_exception_becomes_stale_when_code_imports_dependency(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "import uvicorn\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    exceptions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    failures = gate.audit([usage], exceptions)
    assert any("production code now imports it" in failure for failure in failures)


def test_exception_becomes_stale_when_dependency_is_removed(gate, tmp_path) -> None:
    _write_package(tmp_path, ["httpx>=0.27"], "import httpx\n")
    usage = gate.discover(tmp_path, {"httpx": frozenset({"httpx"})})[0]
    exceptions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    failures = gate.audit([usage], exceptions)
    assert any("dependency was removed" in failure for failure in failures)


def test_exception_requires_category_owner_and_specific_rationale(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    exceptions = {
        usage.manifest: {
            "uvicorn": {
                "category": "OTHER",
                "owner": "",
                "rationale": "needed",
            }
        }
    }
    failures = gate.audit([usage], exceptions)
    assert any("invalid/missing exception category" in failure for failure in failures)
    assert any("missing an owner" in failure for failure in failures)
    assert any("too vague" in failure for failure in failures)

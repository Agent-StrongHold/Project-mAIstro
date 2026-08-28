from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def gate():
    path = Path(__file__).resolve().parents[1] / "scripts" / "pip_audit_gate.py"
    spec = importlib.util.spec_from_file_location("pip_audit_gate", path)
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
        f'[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = [\n{deps}\n]\n'
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


def test_local_workspace_distribution_mapping_beats_editable_metadata_gap(gate, tmp_path) -> None:
    core = tmp_path / "packages" / "core"
    (core / "src" / "shared_ns").mkdir(parents=True)
    (core / "pyproject.toml").write_text(
        '[project]\nname = "core-dist"\nversion = "0.1.0"\ndependencies = []\n'
    )
    app = tmp_path / "packages" / "app"
    (app / "src" / "app").mkdir(parents=True)
    (app / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\ndependencies = ["core-dist"]\n'
    )
    (app / "src" / "app" / "main.py").write_text("from shared_ns import feature\n")
    usages = gate.discover(tmp_path, {})
    app_usage = next(usage for usage in usages if usage.manifest.endswith("app/pyproject.toml"))
    assert app_usage.unused == frozenset()


def test_missing_disposition_for_unused_runtime_dependency_fails(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    failures = gate.audit([usage], {})
    assert any("uvicorn is a direct runtime dependency" in failure for failure in failures)


def test_reviewed_non_import_runtime_disposition_passes(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    dispositions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    assert gate.audit([usage], dispositions) == []


def test_pending_cleanup_disposition_passes_with_concrete_owner(gate, tmp_path) -> None:
    _write_package(tmp_path, ["langfuse>=3"], "pass\n")
    usage = gate.discover(tmp_path, {"langfuse": frozenset({"langfuse"})})[0]
    dispositions = {
        usage.manifest: {
            "langfuse": {
                "category": "PENDING_CLEANUP",
                "owner": "#514",
                "rationale": "Pre-existing unimported dependency is assigned to #514 for removal or ownership correction.",
            }
        }
    }
    assert gate.audit([usage], dispositions) == []


def test_disposition_becomes_stale_when_code_imports_dependency(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "import uvicorn\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    dispositions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    failures = gate.audit([usage], dispositions)
    assert any("production code now imports it" in failure for failure in failures)


def test_disposition_becomes_stale_when_dependency_is_removed(gate, tmp_path) -> None:
    _write_package(tmp_path, ["httpx>=0.27"], "import httpx\n")
    usage = gate.discover(tmp_path, {"httpx": frozenset({"httpx"})})[0]
    dispositions = {
        usage.manifest: {
            "uvicorn": {
                "category": "ENTRYPOINT_RUNTIME",
                "owner": "#352",
                "rationale": "The production container invokes the uvicorn console entry point directly.",
            }
        }
    }
    failures = gate.audit([usage], dispositions)
    assert any("dependency was removed" in failure for failure in failures)


def test_disposition_requires_category_owner_and_specific_rationale(gate, tmp_path) -> None:
    _write_package(tmp_path, ["uvicorn>=0.32"], "pass\n")
    usage = gate.discover(tmp_path, {"uvicorn": frozenset({"uvicorn"})})[0]
    dispositions = {
        usage.manifest: {
            "uvicorn": {
                "category": "OTHER",
                "owner": "",
                "rationale": "needed",
            }
        }
    }
    failures = gate.audit([usage], dispositions)
    assert any("invalid/missing disposition category" in failure for failure in failures)
    assert any("missing an owner" in failure for failure in failures)
    assert any("too vague" in failure for failure in failures)

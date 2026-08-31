"""Render and update contracts for the Conductor-shaped Copier template."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from tests.templates.conftest import CANONICAL_ENGINE_SRC

ENGINE_REF = "74218cf762d7b704732b3a22ff1dd90e49273aee"
ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.contract("behavioral"),
    pytest.mark.scope("integration"),
]


def _answers(project: Path) -> dict[str, object]:
    loaded = yaml.safe_load((project / ".copier-answers.yml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_nested_questionnaire_matches_root_dispatcher() -> None:
    nested = yaml.safe_load(
        (ROOT / "templates/single-tenant-multi-user/copier.yml").read_text(encoding="utf-8")
    )
    dispatcher = yaml.safe_load((ROOT / "copier.yml").read_text(encoding="utf-8"))
    knobs = {"users_max", "auth_backend", "channels", "host_target"}

    assert knobs <= nested.keys()
    assert all(nested[name]["default"] == dispatcher[name]["default"] for name in knobs)


def test_defaults_render_a_runnable_scaffold(render_template, generated_tests) -> None:
    rendered = render_template(
        "single-tenant-multi-user",
        {"project_slug": "household-ai"},
    )
    project = rendered.destination

    expected = {
        ".env.example",
        ".copier-answers.yml",
        ".gitignore",
        "Dockerfile",
        "README.md",
        "cosmic-ray.toml",
        "deploy/compose.yml",
        "docs/adr/ADR-001-generated-product-baseline.md",
        "docs/specs/SPEC-000-template.md",
        "pyproject.toml",
        "src/household_ai/__init__.py",
        "src/household_ai/config.py",
        "src/household_ai/main.py",
        "tests/test_config.py",
        "tests/test_copier_origin.py",
    }
    assert expected <= {
        path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file()
    }
    assert not (project / "deploy/systemd/household-ai.service").exists()

    answers = _answers(project)
    assert answers["product_template"] == "single-tenant-multi-user"
    assert answers["users_max"] == 5
    assert answers["auth_backend"] == "local"
    assert answers["channels"] == ["web"]
    assert answers["host_target"] == "podman"

    metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]
    assert len(dependencies) == 1
    assert f"@{ENGINE_REF}#subdirectory=packages/maistro-core" in dependencies[0]
    assert metadata["tool"]["hatch"]["metadata"]["allow-direct-references"] is True

    environment = (project / ".env.example").read_text(encoding="utf-8")
    compose = (project / "deploy/compose.yml").read_text(encoding="utf-8")
    adr = (project / "docs/adr/ADR-001-generated-product-baseline.md").read_text(encoding="utf-8")
    mutation = (project / "cosmic-ray.toml").read_text(encoding="utf-8")
    rendered_compose = yaml.safe_load(compose)
    assert (
        rendered_compose["services"]["household-ai"]["environment"]["MAISTRO_LOCAL_AUTH_SECRET"]
        == "${MAISTRO_LOCAL_AUTH_SECRET:?set MAISTRO_LOCAL_AUTH_SECRET}"
    )
    assert "MAISTRO_LOCAL_AUTH_SECRET=" in environment
    assert 'MAISTRO_LOCAL_AUTH_SECRET: "${MAISTRO_LOCAL_AUTH_SECRET:?' in compose
    assert "sk-" not in environment
    assert "maistro-engine#ADR-019" in adr
    assert "maistro-engine#ADR-032" in adr
    assert "maistro-engine#ADR-033" in adr
    assert 'module-path = "src/household_ai/config.py"' in mutation
    assert "--timeout=20 -q -x" in mutation
    generated_tests(project)


def test_template_origin_rejects_drift(render_template) -> None:
    rendered = render_template(
        "single-tenant-multi-user",
        {"project_slug": "household-ai"},
    )
    project = rendered.destination
    answers_path = project / ".copier-answers.yml"
    answers = yaml.safe_load(answers_path.read_text(encoding="utf-8"))
    assert isinstance(answers, dict)
    answers["_src_path"] = "https://evil.example/fork.git"
    answers_path.write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_copier_origin.py", "-q"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert CANONICAL_ENGINE_SRC in result.stdout + result.stderr


def test_alternate_knobs_survive_copier_update(render_template, generated_tests) -> None:
    rendered = render_template(
        "single-tenant-multi-user",
        {"project_slug": "household-ai"},
    )
    rendered.update(
        {
            "users_max": 25,
            "auth_backend": "keycloak",
            "channels": ["voice", "email"],
            "host_target": "systemd",
        }
    )
    project = rendered.destination

    assert (project / "round-trip.txt").read_text(encoding="utf-8") == "updated household-ai\n"
    assert (project / "deploy/systemd/household-ai.service").is_file()
    assert not (project / "Dockerfile").exists()
    assert not (project / "deploy/compose.yml").exists()

    answers = _answers(project)
    assert answers["users_max"] == 25
    assert answers["auth_backend"] == "keycloak"
    assert answers["channels"] == ["voice", "email"]
    assert answers["host_target"] == "systemd"

    environment = (project / ".env.example").read_text(encoding="utf-8")
    assert "KEYCLOAK_ISSUER_URL=" in environment
    assert "KEYCLOAK_CLIENT_SECRET=" in environment
    assert "VOICE_SERVICE_KEY=" in environment
    assert "SMTP_PASSWORD=" in environment
    assert "MAISTRO_LOCAL_AUTH_SECRET" not in environment
    generated_tests(project)

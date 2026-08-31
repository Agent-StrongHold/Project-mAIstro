"""Render and update contracts for the autonoetic Copier template."""

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
    nested = yaml.safe_load((ROOT / "templates/autonoetic/copier.yml").read_text(encoding="utf-8"))
    dispatcher = yaml.safe_load((ROOT / "copier.yml").read_text(encoding="utf-8"))
    knobs = {"awareness_loop_hz", "self_model", "memory_consolidator", "dossier_store"}

    assert knobs <= nested.keys()
    assert all(nested[name]["default"] == dispatcher[name]["default"] for name in knobs)


def test_defaults_render_a_runnable_scaffold(render_template, generated_tests) -> None:
    rendered = render_template("autonoetic", {"project_slug": "continuity-agent"})
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
        "src/continuity_agent/__init__.py",
        "src/continuity_agent/config.py",
        "src/continuity_agent/main.py",
        "tests/test_config.py",
        "tests/test_copier_origin.py",
    }
    assert expected <= {
        path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file()
    }
    assert not (project / "src/continuity_agent/memory_consolidator.py").exists()

    answers = _answers(project)
    assert answers["product_template"] == "autonoetic"
    assert answers["awareness_loop_hz"] == 1
    assert answers["self_model"] == "minimal"
    assert answers["memory_consolidator"] == "off"
    assert answers["dossier_store"] == "fs"

    metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]
    assert len(dependencies) == 2
    assert all(f"@{ENGINE_REF}#subdirectory=packages/" in dependency for dependency in dependencies)
    assert metadata["tool"]["hatch"]["metadata"]["allow-direct-references"] is True

    environment = (project / ".env.example").read_text(encoding="utf-8")
    compose = (project / "deploy/compose.yml").read_text(encoding="utf-8")
    adr = (project / "docs/adr/ADR-001-generated-product-baseline.md").read_text(encoding="utf-8")
    mutation = (project / "cosmic-ray.toml").read_text(encoding="utf-8")
    rendered_compose = yaml.safe_load(compose)
    assert rendered_compose["services"]["continuity-agent"]["volumes"] == [
        "dossier-data:/data/dossier:rw"
    ]
    assert "dossier-data" in rendered_compose["volumes"]
    assert "LITELLM_VIRTUAL_KEY=" in environment
    assert "sk-" not in environment
    assert "dossier-data:/data/dossier:rw" in compose
    assert "OBSIDIAN_VAULT_PATH" not in compose
    assert "maistro-engine#ADR-019" in adr
    assert "maistro-engine#ADR-032" in adr
    assert "maistro-engine#ADR-033" in adr
    assert 'module-path = "src/continuity_agent/config.py"' in mutation
    assert "--timeout=20 -q -x" in mutation
    generated_tests(project)


def test_template_origin_rejects_drift(render_template) -> None:
    rendered = render_template("autonoetic", {"project_slug": "continuity-agent"})
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
    rendered = render_template("autonoetic", {"project_slug": "continuity-agent"})
    rendered.update(
        {
            "awareness_loop_hz": 20,
            "self_model": "hexaco",
            "memory_consolidator": "on",
            "dossier_store": "obsidian",
        }
    )
    project = rendered.destination

    assert (project / "round-trip.txt").read_text(encoding="utf-8") == (
        "updated continuity-agent\n"
    )
    assert (project / "src/continuity_agent/memory_consolidator.py").is_file()

    answers = _answers(project)
    assert answers["awareness_loop_hz"] == 20
    assert answers["self_model"] == "hexaco"
    assert answers["memory_consolidator"] == "on"
    assert answers["dossier_store"] == "obsidian"

    environment = (project / ".env.example").read_text(encoding="utf-8")
    compose = (project / "deploy/compose.yml").read_text(encoding="utf-8")
    rendered_compose = yaml.safe_load(compose)
    assert "OBSIDIAN_VAULT_PATH=" in environment
    assert "${OBSIDIAN_VAULT_PATH:?" in compose
    assert "dossier-data:/data/dossier:rw" not in compose
    assert rendered_compose["services"]["continuity-agent"]["volumes"] == [
        "${OBSIDIAN_VAULT_PATH:?set OBSIDIAN_VAULT_PATH}:/data/dossier:rw"
    ]
    assert "volumes" not in rendered_compose
    generated_tests(project)

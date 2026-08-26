"""Static halves of the shipped-image smoke contract.

The docker-build job supplies the behavioral half by booting the exact image.
These assertions prevent the Compose, installer, and image declarations from
drifting independently between those comparatively expensive runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_18_mount_and_pgdata_move_together() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]

    assert postgres["environment"]["PGDATA"] == "/var/lib/postgresql/18/docker"
    assert "pgdata:/var/lib/postgresql" in postgres["volumes"]
    assert all(not mount.endswith(":/var/lib/postgresql/data") for mount in postgres["volumes"])


def test_engine_compose_passes_every_required_auth_value() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["maistro-engine"]["environment"]

    assert any(item.startswith("API_KEYS=") for item in environment)
    assert any(item.startswith("ROUTER_API_KEY=") for item in environment)


def test_installer_example_uses_the_settings_json_representation() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    raw = next(
        line.split("=", 1)[1].split("#", 1)[0].strip()
        for line in example.splitlines()
        if line.startswith("API_KEYS=")
    )

    assert json.loads(raw) == []
    assert "ROUTER_API_KEY=" in example


def test_image_pins_supported_python_and_installs_identity() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    python_tags = re.findall(r"^FROM python:(3\.\d+\.\d+)-slim-bookworm", dockerfile, re.MULTILINE)

    assert python_tags == ["3.13.15", "3.13.15"]
    assert "maistro-core[identity,llm,sandbox,observability]" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "maistro_server.entrypoint"]' in dockerfile


def test_docker_build_job_boots_the_image_it_built() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    build = workflow.index("docker build -t maistro-engine:test .")
    boot = workflow.index("maistro-engine:test", build + 1)
    live = workflow.index("/health/live", boot)
    ready = workflow.index("/health/ready", live)

    assert build < boot < live < ready

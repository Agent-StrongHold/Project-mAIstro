"""The Compose resource gate must test effective, non-Swarm limits (#862)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-compose-resources.py"


@pytest.fixture(scope="module")
def gate() -> Any:
    spec = importlib.util.spec_from_file_location("check_compose_resources", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_supported_profiles_pass_the_resource_policy(gate: Any) -> None:
    assert gate.audit() == []


def test_every_service_in_supported_profiles_has_all_four_effective_limits(gate: Any) -> None:
    for path in gate.COMPOSE_FILES:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, service in document.get("services", {}).items():
            assert service["mem_limit"], (path, name)
            assert service["memswap_limit"] == service["mem_limit"], (path, name)
            assert service["pids_limit"] > 0, (path, name)
            assert service["cpus"] > 0, (path, name)
            assert "resources" not in service.get("deploy", {}), (path, name)


def test_missing_or_swarm_only_limits_fail_closed(gate: Any, tmp_path: Path) -> None:
    path = tmp_path / "compose.yml"
    service = {
        "image": "example/app",
        "deploy": {"resources": {"limits": {"memory": "1g", "cpus": "1"}}},
    }
    path.write_text(yaml.safe_dump({"services": {"app": service}}), encoding="utf-8")

    messages = [
        finding.message for finding in gate.check_document(yaml.safe_load(path.read_text()), path)
    ]

    assert any("mem_limit" in message for message in messages)
    assert any("memswap_limit" in message for message in messages)
    assert any("pids_limit" in message for message in messages)
    assert any("cpus" in message for message in messages)
    assert any("deploy.resources" in message for message in messages)


def test_effectively_unbounded_values_are_rejected(gate: Any, tmp_path: Path) -> None:
    path = tmp_path / "compose.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "app": {
                        "mem_limit": "0",
                        "memswap_limit": "unlimited",
                        "pids_limit": 0,
                        "cpus": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    findings = gate.check_document(yaml.safe_load(path.read_text()), path)

    assert {finding.message.split(" ", 1)[0] for finding in findings} >= {
        "mem_limit",
        "memswap_limit",
        "pids_limit",
        "cpus",
    }


def test_copier_compose_templates_carry_the_same_contract() -> None:
    templates = (
        ROOT / "templates/autonoetic/deploy/compose.yml.jinja",
        ROOT
        / "templates/single-tenant-multi-user/deploy/{% if host_target in ['docker', 'podman'] %}compose.yml{% endif %}.jinja",
    )
    for path in templates:
        text = path.read_text(encoding="utf-8")
        assert "mem_limit:" in text, path
        assert "memswap_limit:" in text, path
        assert "pids_limit:" in text, path
        assert "cpus:" in text, path
        assert "deploy:" not in text, path

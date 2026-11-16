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
MiB = 1024 * 1024
GiB = 1024 * MiB

# A service every DEFAULT_POLICY range accepts: finite memory with swap pinned
# to it, a bounded PID budget, and an intentional CPU quota. Used to build
# synthetic profiles whose verdict under the gate is fully known.
IN_POLICY_SERVICE = {
    "image": "example/app",
    "mem_limit": "512m",
    "memswap_limit": "512m",
    "pids_limit": 128,
    "cpus": 1.0,
    # A deploy mapping without deploy.resources is allowed: the gate rejects
    # the Swarm-only resources key, not the whole deploy section.
    "deploy": {"replicas": 1},
}


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


def test_parse_memory_rejects_malformed_and_nonpositive_values(gate: Any) -> None:
    assert gate.parse_memory(True) is None  # bools are ints in Python: refuse
    assert gate.parse_memory(["1g"]) is None  # not a number or string
    assert gate.parse_memory(0) is None  # zero memory is effectively unbounded
    assert gate.parse_memory(-2) is None
    assert gate.parse_memory(float("inf")) is None
    assert gate.parse_memory(262144) == 262144  # bare numbers are bytes
    assert gate.parse_memory("unlimited") is None
    assert gate.parse_memory("") is None
    assert gate.parse_memory("  ") is None
    # A digit string that overflows to infinity is not a finite limit, and a
    # parsed zero is not a positive one — both must fail closed.
    assert gate.parse_memory("1" + "0" * 400 + "b") is None
    assert gate.parse_memory("0b") is None


def test_parse_memory_honours_every_unit_the_grammar_accepts(gate: Any) -> None:
    k = 1024
    cases = {
        "": 1,
        "b": 1,
        "k": k,
        "kb": k,
        "kib": k,
        "m": MiB,
        "mb": MiB,
        "mib": MiB,
        "g": GiB,
        "gb": GiB,
        "gib": GiB,
        "t": k**4,
        "tb": k**4,
        "tib": k**4,
        "p": k**5,
        "pb": k**5,
        "pib": k**5,
        "e": k**6,
        "eb": k**6,
        "eib": k**6,
    }
    for unit, multiplier in cases.items():
        assert gate.parse_memory(f"2{unit}") == 2 * multiplier, unit
    # Docker RAM semantics are binary regardless of the "b" spelling, and the
    # parser is case-insensitive: --memory 2g applies 2147483648.
    assert gate.parse_memory("2G") == 2 * GiB
    assert gate.parse_memory("2GiB") == 2 * GiB


def test_numeric_helper_parsers_are_strict(gate: Any) -> None:
    assert gate._finite_number("2.0") == 2.0
    assert gate._finite_number(0.5) == 0.5
    assert gate._finite_number(True) is None
    assert gate._finite_number(None) is None
    assert gate._finite_number("abc") is None
    assert gate._finite_number("0") is None
    assert gate._finite_number("-1") is None
    assert gate._finite_number("nan") is None
    assert gate._finite_number("inf") is None

    assert gate._integer("128") == 128
    assert gate._integer(512) == 512
    assert gate._integer("12") == 12
    assert gate._integer(True) is None
    assert gate._integer("abc") is None
    assert gate._integer("12.5") is None
    assert gate._integer(12.5) is None
    assert gate._integer(0) is None
    assert gate._integer(-4) is None


def test_non_mapping_service_fails_closed(gate: Any, tmp_path: Path) -> None:
    findings = gate.check_document({"services": {"broken": "nginx"}}, tmp_path / "compose.yml")

    assert [finding.message for finding in findings] == ["is not a service mapping"]


def test_swap_mismatch_and_out_of_policy_values_are_reported(gate: Any, tmp_path: Path) -> None:
    path = tmp_path / "compose.yml"
    swapped = {
        "mem_limit": "1g",
        "memswap_limit": "2g",
        "pids_limit": 999999,
        "cpus": 1.0,
    }
    messages = [
        finding.message for finding in gate.check_document({"services": {"app": swapped}}, path)
    ]

    assert any("memswap_limit must equal mem_limit" in message for message in messages)
    assert any(
        "pids_limit" in message and "outside the safety policy" in message for message in messages
    )

    # Below the DEFAULT_POLICY floor on every axis: exactly one violation per
    # limit, so a floor drop cannot slip through as "just tuning".
    tiny = {"mem_limit": "64b", "memswap_limit": "64b", "pids_limit": 8, "cpus": 0.01}
    messages = [
        finding.message for finding in gate.check_document({"services": {"app": tiny}}, path)
    ]

    assert sum("outside the safety policy" in message for message in messages) == 4


def test_document_level_failures_and_non_string_keys(gate: Any, tmp_path: Path) -> None:
    path = tmp_path / "compose.yml"

    findings = gate.check_document("not-a-mapping", path)

    assert [finding.service for finding in findings] == ["<document>"]
    assert "is not a YAML mapping" in findings[0].message

    # A top-level "services" that is not a mapping carries nothing to check.
    assert gate.check_document({"services": "oops"}, path) == []

    # YAML allows non-string keys; only string-named services are checked.
    document = {"services": {True: "not checked", "app": dict(IN_POLICY_SERVICE)}}
    assert gate.check_document(document, path) == []


def test_audit_reports_missing_and_unparseable_profiles(gate: Any, tmp_path: Path) -> None:
    good = tmp_path / "good.yml"
    good.write_text(
        yaml.safe_dump({"services": {"app": dict(IN_POLICY_SERVICE)}}), encoding="utf-8"
    )
    missing = tmp_path / "missing.yml"
    bad = tmp_path / "bad.yml"
    bad.write_text("services: [unclosed", encoding="utf-8")

    findings = gate.audit((good, missing, bad))

    assert any("supported profile is missing" in finding.message for finding in findings)
    assert any("is not valid YAML" in finding.message for finding in findings)


def test_main_exit_codes_and_output(gate: Any, tmp_path: Path, capsys: Any) -> None:
    root = tmp_path / "repo"
    for relative in gate.COMPOSE_RELATIVE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({"services": {"app": dict(IN_POLICY_SERVICE)}}),
            encoding="utf-8",
        )

    assert gate.main(["--root", str(root)]) == 0
    assert "OK: 8 supported Compose profiles" in capsys.readouterr().out

    broken = root / "docker-compose.yml"
    broken.write_text(
        yaml.safe_dump({"services": {"app": {"image": "example/app"}}}),
        encoding="utf-8",
    )

    assert gate.main(["--root", str(root)]) == 1
    captured = capsys.readouterr().out
    assert "FAIL: 4 Compose resource policy violation(s)" in captured
    assert "mem_limit" in captured

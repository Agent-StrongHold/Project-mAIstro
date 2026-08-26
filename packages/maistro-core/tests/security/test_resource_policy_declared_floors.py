"""Independent security-floor contract for resource policy (#321)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro.security import resource_policy as policy


_DECLARATION = (
    Path(__file__).resolve().parents[4] / "quality" / "security-resource-floors.json"
)


def _declared() -> dict[str, dict[str, int | float | str]]:
    return json.loads(_DECLARATION.read_text(encoding="utf-8"))["floors"]


def test_production_baselines_match_independent_declared_policy() -> None:
    declared = _declared()
    actual = {
        "max_request_body_bytes": policy.BASELINE_MAX_REQUEST_BODY_BYTES,
        "max_webhook_body_bytes": policy.BASELINE_MAX_WEBHOOK_BODY_BYTES,
        "rate_limit_per_minute": policy.BASELINE_RATE_LIMIT_PER_MINUTE,
        "rate_limit_burst": policy.BASELINE_RATE_LIMIT_BURST,
        "circuit_breaker_failure_threshold": policy.BASELINE_CIRCUIT_FAILURE_THRESHOLD,
        "circuit_breaker_recovery_timeout_s": policy.BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
    }

    assert actual == {name: spec["value"] for name, spec in declared.items()}


@pytest.mark.parametrize("name,factor", [("rate_limit_per_minute", 100), ("max_request_body_bytes", 1024)])
def test_known_weakening_mutants_are_rejected(name: str, factor: int) -> None:
    declared = _declared()
    values = {field: spec["value"] for field, spec in declared.items()}
    values[name] = values[name] * factor

    candidate = policy.EffectiveResourcePolicy(**values)

    with pytest.raises(ValueError, match="weakens the declared baseline"):
        policy.validate_resource_policy(candidate)


def test_every_declared_floor_has_the_expected_safety_direction() -> None:
    declared = _declared()
    implementation = {floor.name: floor.smaller_is_tighter for floor in policy._FLOORS}
    expected = {
        name: spec["safer_direction"] == "lower" for name, spec in declared.items()
    }

    assert implementation == expected

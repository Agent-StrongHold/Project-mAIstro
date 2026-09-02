"""Fail-closed contract for M1 pre-cutover behavioral baselines (#463).

This is deliberately test/evidence code, not a product runtime. The fixtures
capture observable behavior before legacy authorities are retired; #459 may
feed observations from the converged spine through the same matcher.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

REQUIRED_COVERAGE = {
    "observable_outputs",
    "lifecycle",
    "durable_ids_provenance",
    "errors_refusals",
    "cancellation",
    "restart",
}
_ALLOWED_COVERAGE_STATES = {"captured", "not-characterized", "not-supported"}
_ALLOWED_EXPECTATIONS = {"equals", "present", "absent", "sequence"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class BaselineContractError(AssertionError):
    """A fixture or observation does not satisfy the locked baseline contract."""


_MISSING = object()


def _lookup(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                index = int(part)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def _validate_header(fixture: Mapping[str, Any]) -> None:
    if fixture.get("schema_version") != 1:
        raise BaselineContractError("schema_version must be 1")
    if fixture.get("locked") is not True:
        raise BaselineContractError("baseline fixture must be locked")
    if fixture.get("version") != 1:
        raise BaselineContractError("baseline fixture version must be 1")
    for field in ("baseline_id", "product", "change_reason"):
        value = fixture.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BaselineContractError(f"{field} must be a non-empty string")


def _validate_capture(fixture: Mapping[str, Any]) -> None:
    captured = fixture.get("captured_from")
    if not isinstance(captured, Mapping):
        raise BaselineContractError("captured_from must be an object")
    if not _SHA40.fullmatch(str(captured.get("commit", ""))):
        raise BaselineContractError("captured_from.commit must be a 40-character git SHA")
    evidence = captured.get("evidence_tests")
    if not isinstance(evidence, list) or not evidence:
        raise BaselineContractError("captured_from.evidence_tests must be non-empty")
    if not all(isinstance(ref, str) and "::test_" in ref for ref in evidence):
        raise BaselineContractError("every evidence reference must name a pytest test")


def _validate_coverage_record(dimension: str, record: Any) -> None:
    if not isinstance(record, Mapping):
        raise BaselineContractError(f"coverage {dimension} must be an object")
    if record.get("state") not in _ALLOWED_COVERAGE_STATES:
        raise BaselineContractError(f"coverage {dimension} has an invalid state")
    reason = record.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise BaselineContractError(f"coverage {dimension} requires a reason")


def _validate_coverage(fixture: Mapping[str, Any]) -> None:
    coverage = fixture.get("behavior_coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != REQUIRED_COVERAGE:
        raise BaselineContractError("behavior_coverage must name every required dimension")
    for dimension, record in coverage.items():
        _validate_coverage_record(str(dimension), record)


def _validate_scenario(scenario: Any, seen: set[str]) -> None:
    if not isinstance(scenario, Mapping):
        raise BaselineContractError("scenario must be an object")
    scenario_id = scenario.get("id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise BaselineContractError("scenario id must be non-empty")
    if scenario_id in seen:
        raise BaselineContractError(f"duplicate scenario id: {scenario_id}")
    seen.add(scenario_id)
    if not isinstance(scenario.get("input"), Mapping):
        raise BaselineContractError(f"{scenario_id}: input must be an object")
    expectation = scenario.get("expect")
    if not isinstance(expectation, Mapping) or not expectation:
        raise BaselineContractError(f"{scenario_id}: expect must be non-empty")
    unknown = set(expectation) - _ALLOWED_EXPECTATIONS
    if unknown:
        raise BaselineContractError(f"{scenario_id}: unsupported expectations: {sorted(unknown)}")
    if not isinstance(scenario.get("example_observation"), Mapping):
        raise BaselineContractError(f"{scenario_id}: example_observation must be an object")


def _validate_scenarios(fixture: Mapping[str, Any]) -> None:
    scenarios = fixture.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise BaselineContractError("scenarios must be non-empty")
    seen: set[str] = set()
    for scenario in scenarios:
        _validate_scenario(scenario, seen)


def validate_fixture(fixture: Mapping[str, Any]) -> None:
    """Validate one immutable baseline fixture and reject underspecified records."""
    _validate_header(fixture)
    _validate_capture(fixture)
    _validate_coverage(fixture)
    _validate_scenarios(fixture)


def _assert_equals(
    scenario_id: str, expectation: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for path, expected in expectation.get("equals", {}).items():
        actual = _lookup(observation, path)
        if actual is _MISSING:
            raise BaselineContractError(f"{scenario_id}: missing required path {path}")
        if actual != expected:
            raise BaselineContractError(
                f"{scenario_id}: {path} expected {expected!r}, observed {actual!r}"
            )


def _assert_present(
    scenario_id: str, expectation: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for path in expectation.get("present", []):
        actual = _lookup(observation, path)
        if actual is _MISSING or actual is None:
            raise BaselineContractError(f"{scenario_id}: required value {path} is absent")


def _assert_absent(
    scenario_id: str, expectation: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for path in expectation.get("absent", []):
        if _lookup(observation, path) is not _MISSING:
            raise BaselineContractError(f"{scenario_id}: forbidden value {path} is present")


def _assert_sequences(
    scenario_id: str, expectation: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for path, expected in expectation.get("sequence", {}).items():
        actual = _lookup(observation, path)
        if actual is _MISSING:
            raise BaselineContractError(f"{scenario_id}: missing sequence {path}")
        if list(actual) != list(expected):
            raise BaselineContractError(
                f"{scenario_id}: sequence {path} expected {expected!r}, observed {actual!r}"
            )


def assert_observation_matches(scenario: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
    """Assert semantic parity for the expectation operators used by a scenario."""
    expectation = scenario["expect"]
    scenario_id = str(scenario.get("id", "<unknown>"))
    _assert_equals(scenario_id, expectation, observation)
    _assert_present(scenario_id, expectation, observation)
    _assert_absent(scenario_id, expectation, observation)
    _assert_sequences(scenario_id, expectation, observation)


def incompatible_copy(
    scenario: Mapping[str, Any], dotted_path: str, replacement: Any
) -> dict[str, Any]:
    """Return a deep-copied example with one path replaced for planted negatives."""
    candidate = copy.deepcopy(dict(scenario["example_observation"]))
    parts = dotted_path.split(".")
    current: Any = candidate
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    leaf = parts[-1]
    if isinstance(current, list):
        current[int(leaf)] = replacement
    else:
        current[leaf] = replacement
    return candidate

"""Contract tests for immutable M1 pre-cutover behavioral baselines (#463)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from tests.golden_baselines.contract import (
    BaselineContractError,
    assert_observation_matches,
    incompatible_copy,
    validate_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "tests" / "golden_baselines"
MANIFEST = BASELINES / "manifest.json"

SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ratchet_provenance import resolve_baseline  # noqa: E402


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _fixtures() -> list[tuple[dict, Path]]:
    manifest = _manifest()
    rows: list[tuple[dict, Path]] = []
    for record in manifest["fixtures"]:
        path = BASELINES / record["path"]
        rows.append((json.loads(path.read_text(encoding="utf-8")), path))
    return rows


def _scenario(product: str, scenario_id: str) -> dict:
    for fixture, _ in _fixtures():
        if fixture["product"] != product:
            continue
        for scenario in fixture["scenarios"]:
            if scenario["id"] == scenario_id:
                return scenario
    raise AssertionError(f"missing scenario {product}:{scenario_id}")


def test_manifest_covers_every_required_pre_cutover_product() -> None:
    manifest = _manifest()
    products = [record["product"] for record in manifest["fixtures"]]

    assert manifest["schema_version"] == 1
    assert manifest["baseline_set"] == "m1-pre-cutover-v1"
    assert set(products) == set(manifest["required_products"])
    assert products == ["builders", "conductor", "evolve", "schedules"]


def test_fixture_bytes_match_the_locked_manifest_hashes() -> None:
    for record in _manifest()["fixtures"]:
        payload = (BASELINES / record["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"]


def _assert_preserved_locked_records(trusted: dict, candidate: dict, directory: Path) -> None:
    """An old oracle is immutable even when a candidate also changes its hash."""
    candidate_records = {row["path"]: row for row in candidate["fixtures"]}
    assert len(candidate_records) == len(candidate["fixtures"]), "duplicate fixture path"
    assert candidate["captured_from_commit"] == trusted["captured_from_commit"], (
        "capture provenance changed"
    )
    for record in trusted["fixtures"]:
        path = record["path"]
        assert candidate_records.get(path) == record, f"locked fixture record changed: {path}"
        fixture = directory / path
        assert fixture.is_file(), f"locked fixture missing: {path}"
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == record["sha256"], (
            f"locked fixture bytes changed: {path}"
        )


def test_locked_fixture_records_preserve_the_independent_base() -> None:
    baseline = resolve_baseline(MANIFEST, root=ROOT)
    assert baseline.origin == "base" and baseline.base_sha, "independent golden baseline required"
    trusted = baseline.loads()
    assert isinstance(trusted, dict), "trusted golden manifest is missing or invalid"
    _assert_preserved_locked_records(trusted, _manifest(), BASELINES)


def test_candidate_cannot_rewrite_fixture_and_matching_manifest(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_bytes(b"original")
    trusted = {
        "captured_from_commit": "a" * 40,
        "fixtures": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
    }
    path.write_bytes(b"changed")
    candidate = {
        "captured_from_commit": trusted["captured_from_commit"],
        "fixtures": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
    }
    # Candidate-only checksum verification would pass.
    assert candidate["fixtures"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(AssertionError, match="locked fixture record changed"):
        _assert_preserved_locked_records(trusted, candidate, tmp_path)


def test_every_fixture_is_locked_and_fail_closed_schema_valid() -> None:
    for fixture, _ in _fixtures():
        validate_fixture(fixture)

    unlocked = dict(_fixtures()[0][0])
    unlocked["locked"] = False
    with pytest.raises(BaselineContractError, match="must be locked"):
        validate_fixture(unlocked)


def test_capture_provenance_is_pinned_and_worktree_independent() -> None:
    """Retiring old characterization tests must not erase the captured oracle."""
    manifest = _manifest()
    capture_commit = manifest["captured_from_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", capture_commit)

    references: set[tuple[str, str]] = set()
    for fixture, _ in _fixtures():
        assert fixture["captured_from"]["commit"] == capture_commit
        for reference in fixture["captured_from"]["evidence_tests"]:
            relative_path, test_name = reference.split("::", 1)
            assert relative_path.endswith(".py")
            assert test_name.startswith("test_")
            key = (capture_commit, reference)
            assert key not in references
            references.add(key)

    assert references


def test_baseline_and_scenario_ids_are_globally_unique() -> None:
    baseline_ids: set[str] = set()
    scenario_ids: set[tuple[str, str]] = set()

    for fixture, _ in _fixtures():
        assert fixture["baseline_id"] not in baseline_ids
        baseline_ids.add(fixture["baseline_id"])
        for scenario in fixture["scenarios"]:
            key = (fixture["product"], scenario["id"])
            assert key not in scenario_ids
            scenario_ids.add(key)


def test_captured_examples_satisfy_their_own_behavior_contracts() -> None:
    for fixture, _ in _fixtures():
        for scenario in fixture["scenarios"]:
            assert_observation_matches(scenario, scenario["example_observation"])


def test_semantically_incompatible_builders_retry_is_rejected() -> None:
    scenario = _scenario("builders", "retry_keeps_logical_run")
    candidate = incompatible_copy(scenario, "request_after.run_id", "builders-run-2")

    with pytest.raises(BaselineContractError, match=re.escape("request_after.run_id")):
        assert_observation_matches(scenario, candidate)


def test_schedule_candidate_without_durable_run_identity_is_rejected() -> None:
    scenario = _scenario("schedules", "fire_produces_canonical_run_and_provenance")
    candidate = incompatible_copy(scenario, "audit.run_id", None)

    with pytest.raises(BaselineContractError, match=re.escape("audit.run_id")):
        assert_observation_matches(scenario, candidate)

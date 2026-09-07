"""Trusted-base compatibility-window fitness for canonical contract changes (#461)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONTRACTS = _REPO_ROOT / "quality" / "compatibility-contracts.json"
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ratchet_provenance import RatchetProvenanceError, resolve_baseline  # noqa: E402

_DURABLE_STRATEGIES = frozenset(
    {"dual-read", "schema-migration", "translation-adapter", "version-negotiation"}
)
_NON_PERSISTED_STRATEGIES = frozenset(
    {"import-alias", "translation-adapter", "version-negotiation"}
)
_REQUIRED_RECORD_FIELDS = frozenset(
    {
        "old_identity",
        "replacement_identity",
        "scope",
        "persisted_data",
        "strategy",
        "migration",
        "deprecation_window",
        "owner",
        "removal_condition",
        "release_note",
    }
)


def _load(path: Path = _CONTRACTS) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), "compatibility contract registry must be an object"
    return value


def _records(document: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("compatibility_aliases", "compatibility_migrations"):
        raw = document.get(key)
        if not isinstance(raw, list):
            raise AssertionError(f"{key} must be a list")
        if not all(isinstance(item, dict) for item in raw):
            raise AssertionError(f"{key} entries must be objects")
        records.extend(raw)
    return records


def _canonical_map(document: dict[str, Any]) -> dict[str, frozenset[str]]:
    raw = document.get("canonical_surface")
    if not isinstance(raw, list):
        raise AssertionError("canonical_surface must be a list")
    result: dict[str, frozenset[str]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise AssertionError("canonical_surface entries must be objects")
        identity = entry.get("identity")
        fields = entry.get("required_fields")
        if not isinstance(identity, str) or not identity:
            raise AssertionError("canonical surface identity must be non-empty")
        if not isinstance(fields, list) or not all(
            isinstance(field, str) and field for field in fields
        ):
            raise AssertionError(f"canonical surface {identity} has invalid required_fields")
        result[identity] = frozenset(fields)
    return result


def _policy_violations(policy: dict[str, Any]) -> list[str]:
    # These sets are executable policy, not candidate-extensible configuration.
    # The JSON mirrors them for reviewers, but cannot authorize a weaker rule by
    # adding `import-alias` to the persisted list in the same PR it is judging.
    violations: list[str] = []
    if set(policy.get("persisted_strategies", [])) != _DURABLE_STRATEGIES:
        violations.append("persisted strategy policy differs from the hard-coded durable boundary")
    if set(policy.get("non_persisted_strategies", [])) != _NON_PERSISTED_STRATEGIES:
        violations.append("non-persisted strategy policy differs from the hard-coded boundary")
    return violations


def _invalid_record_identity(record: dict[str, Any]) -> list[str] | None:
    """Return fatal identity violations, or None when the identity is usable."""
    missing = _REQUIRED_RECORD_FIELDS - record.keys()
    label = str(record.get("old_identity", "<unknown>"))
    if missing:
        return [f"compatibility record {label} missing: {', '.join(sorted(missing))}"]
    old_identity = record["old_identity"]
    if not isinstance(old_identity, str) or not old_identity.strip():
        return ["compatibility record has invalid old_identity"]
    return None


def _required_text_field_violations(record: dict[str, Any], old_identity: str) -> list[str]:
    violations: list[str] = []
    for field in (
        "scope",
        "strategy",
        "migration",
        "deprecation_window",
        "owner",
        "removal_condition",
        "release_note",
    ):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            violations.append(f"compatibility record {old_identity} requires non-empty {field}")
    return violations


def _persisted_evidence_violations(record: dict[str, Any], *, evidence_root: Path) -> list[str]:
    old_identity = record["old_identity"]
    fixture = record.get("fixture")
    loader_test = record.get("loader_test")
    if not isinstance(fixture, str) or not fixture.strip():
        return [f"persisted compatibility record {old_identity} requires fixture"]
    if not isinstance(loader_test, str) or not loader_test.strip():
        return [f"persisted compatibility record {old_identity} requires loader_test"]
    violations: list[str] = []
    fixture_path = evidence_root / fixture
    loader_path = evidence_root / loader_test
    if not fixture_path.is_file():
        violations.append(f"persisted compatibility fixture does not exist: {fixture}")
    if not loader_path.is_file():
        violations.append(f"persisted compatibility loader test does not exist: {loader_test}")
    elif Path(fixture).name not in loader_path.read_text(encoding="utf-8"):
        violations.append(
            f"persisted compatibility loader test {loader_test} does not reference {Path(fixture).name}"
        )
    return violations


def _record_violations(record: dict[str, Any], *, seen: set[str], evidence_root: Path) -> list[str]:
    fatal = _invalid_record_identity(record)
    if fatal is not None:
        return fatal

    violations: list[str] = []
    old_identity = record["old_identity"]
    replacement = record["replacement_identity"]
    if old_identity in seen:
        violations.append(f"duplicate compatibility disposition for {old_identity}")
    seen.add(old_identity)
    if not isinstance(replacement, str) or not replacement.strip():
        violations.append(f"compatibility record {old_identity} has invalid replacement_identity")

    violations.extend(_required_text_field_violations(record, old_identity))

    persisted = record["persisted_data"]
    if not isinstance(persisted, bool):
        violations.append(f"compatibility record {old_identity} persisted_data must be boolean")
        return violations
    strategy = record["strategy"]
    allowed = _DURABLE_STRATEGIES if persisted else _NON_PERSISTED_STRATEGIES
    if strategy not in allowed:
        violations.append(f"compatibility record {old_identity} has unsafe strategy {strategy}")

    if persisted:
        violations.extend(_persisted_evidence_violations(record, evidence_root=evidence_root))
    return violations


def _record_shape_violations(document: dict[str, Any], *, evidence_root: Path) -> list[str]:
    policy = document.get("policy")
    if not isinstance(policy, dict):
        return ["compatibility contract registry requires policy object"]

    violations: list[str] = _policy_violations(policy)
    seen: set[str] = set()
    for record in _records(document):
        violations.extend(_record_violations(record, seen=seen, evidence_root=evidence_root))
    return violations


def _baseline_removal_violations(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Compare candidate registry to trusted-base canonical surface."""
    base_surface = _canonical_map(baseline)
    candidate_surface = _canonical_map(candidate)
    dispositions = {
        record["old_identity"]
        for record in _records(candidate)
        if isinstance(record.get("old_identity"), str)
    }

    violations: list[str] = []
    for identity, base_fields in base_surface.items():
        if identity not in candidate_surface:
            if identity not in dispositions:
                violations.append(
                    f"trusted-base canonical type disappeared without compatibility disposition: {identity}"
                )
            continue
        removed = base_fields - candidate_surface[identity]
        for field in sorted(removed):
            old_field = f"{identity}.{field}"
            if old_field not in dispositions:
                violations.append(
                    "trusted-base canonical field disappeared without compatibility disposition: "
                    + old_field
                )
    return violations


def _trusted_baseline() -> dict[str, Any]:
    try:
        baseline = resolve_baseline(_CONTRACTS)
        value = baseline.loads(default=None)
    except RatchetProvenanceError as exc:
        raise AssertionError(f"could not resolve trusted compatibility baseline: {exc}") from exc
    if value is None:
        # Bootstrap is legitimate only when the base revision predates this
        # registry. Current-tree validation still runs in that case.
        return {"canonical_surface": []}
    if not isinstance(value, dict):
        raise AssertionError(
            f"trusted compatibility baseline from {baseline.source} is not an object"
        )
    return value


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_compatibility_registry_uses_trusted_base_and_durable_evidence() -> None:
    candidate = _load()
    violations = _record_shape_violations(candidate, evidence_root=_REPO_ROOT)
    violations.extend(_baseline_removal_violations(_trusted_baseline(), candidate))

    canonical = _canonical_map(candidate)
    invocation = "capabilities/invocation.py::Invocation"
    if invocation not in canonical:
        violations.append("canonical Invocation identity is missing from compatibility surface")
    elif not {
        "invocation_id",
        "run_id",
        "node_run_id",
        "attempt_id",
        "effect_key",
        "status",
    }.issubset(canonical[invocation]):
        violations.append("canonical Invocation identity/linkage fields are incomplete")

    assert not violations, "compatibility-window violation(s):\n" + "\n".join(violations)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_persisted_migration_requires_real_fixture_loader_evidence(tmp_path: Path) -> None:
    document: dict[str, Any] = {
        "policy": {
            "persisted_strategies": sorted(_DURABLE_STRATEGIES),
            "non_persisted_strategies": sorted(_NON_PERSISTED_STRATEGIES),
        },
        "canonical_surface": [],
        "compatibility_aliases": [],
        "compatibility_migrations": [
            {
                "old_identity": "model.py::Thing.old_id",
                "replacement_identity": "model.py::Thing.thing_id",
                "scope": "persisted-record",
                "persisted_data": True,
                "strategy": "schema-migration",
                "migration": "Read old_id and write thing_id without changing identity meaning.",
                "deprecation_window": "one release",
                "owner": "#461",
                "removal_condition": "all old fixtures migrate",
                "release_note": "old_id renamed to thing_id",
            }
        ],
    }
    violations = _record_shape_violations(document, evidence_root=tmp_path)
    assert any("requires fixture" in item for item in violations)

    fixture = tmp_path / "legacy-thing.json"
    fixture.write_text('{"old_id":"stable-1"}\n', encoding="utf-8")
    loader = tmp_path / "test_legacy_thing.py"
    loader.write_text('FIXTURE = "legacy-thing.json"\n', encoding="utf-8")
    record = document["compatibility_migrations"][0]
    record["fixture"] = fixture.name
    record["loader_test"] = loader.name
    assert _record_shape_violations(document, evidence_root=tmp_path) == []

    # Candidate policy text cannot self-authorize import-only handling of
    # durable data: the executable set above remains the authority.
    document["policy"]["persisted_strategies"].append("import-alias")
    record["strategy"] = "import-alias"
    violations = _record_shape_violations(document, evidence_root=tmp_path)
    assert any("hard-coded durable boundary" in item for item in violations)
    assert any("unsafe strategy import-alias" in item for item in violations)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_trusted_base_removal_requires_explicit_disposition() -> None:
    baseline = {
        "canonical_surface": [
            {"identity": "model.py::Thing", "required_fields": ["thing_id", "legacy_name"]}
        ]
    }
    candidate: dict[str, Any] = {
        "canonical_surface": [{"identity": "model.py::Thing", "required_fields": ["thing_id"]}],
        "compatibility_aliases": [],
        "compatibility_migrations": [],
    }
    violations = _baseline_removal_violations(baseline, candidate)
    assert violations == [
        "trusted-base canonical field disappeared without compatibility disposition: "
        "model.py::Thing.legacy_name"
    ]

    candidate["compatibility_migrations"] = [{"old_identity": "model.py::Thing.legacy_name"}]
    assert _baseline_removal_violations(baseline, candidate) == []

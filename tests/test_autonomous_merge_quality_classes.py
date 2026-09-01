from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-autonomous-merge.py"
REGISTRY = ROOT / "quality" / "branch-independence.json"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge_quality_classes", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def cf(path: str, status: str = "M", old_path: str | None = None):
    return mod.ChangedFile(status=status, path=path, old_path=old_path)


def _registry_payload() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _write_registry(tmp_path: Path, payload: object) -> Path:
    registry = tmp_path / "branch-independence.json"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    return registry


def _assess_wiring_reads():
    return mod.assess(
        [cf("quality/wiring-reads-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )


def test_base_derived_quality_evidence_is_yellow_not_red() -> None:
    result = _assess_wiring_reads()

    assert result.risk == "yellow"
    assert not result.eligible
    assert not result.red_reasons
    assert result.yellow_reasons == [
        "branch-independent quality evidence changed (base_derived): "
        "quality/wiring-reads-baseline.json"
    ]


def test_merge_group_may_carry_base_derived_quality_evidence() -> None:
    result = mod.assess([cf("quality/wiring-reads-baseline.json")], "", merge_group=True)

    assert result.risk == "yellow"
    assert result.eligible


def test_quality_specification_stays_red() -> None:
    result = mod.assess(
        [cf("quality/ratchet-authorizations.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "(specification)" in result.red_reasons[0]


def test_unmigrated_quality_aggregate_stays_red() -> None:
    result = mod.assess(
        [cf("quality/vulture-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "(legacy_shared_aggregate)" in result.red_reasons[0]


def test_unknown_quality_surface_fails_closed_red() -> None:
    result = mod.assess([cf("quality/new-output.json")], "", head_ref="chatgpt/x")

    assert result.risk == "red"
    assert not result.eligible
    assert "unclassified" in result.red_reasons[0]


def test_malformed_quality_registry_fails_closed_red(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = tmp_path / "branch-independence.json"
    registry.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", registry)

    result = _assess_wiring_reads()

    assert result.risk == "red"
    assert not result.eligible
    assert "classification unavailable" in result.red_reasons[0]


def test_canonical_registry_schema_is_required_before_yellow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cases = (
        "missing-id",
        "blank-reason",
        "invalid-kind",
        "invalid-path",
    )

    for case in cases:
        payload = _registry_payload()
        surface = next(item for item in payload["surfaces"] if item["id"] == "wiring-reads-baseline")
        if case == "missing-id":
            surface.pop("id")
        elif case == "blank-reason":
            surface["reason"] = "   "
        elif case == "invalid-kind":
            surface["kind"] = "candidate_says_safe"
        else:
            surface["paths"] = ["outside-quality/not-json.txt"]

        registry = _write_registry(tmp_path, payload)
        monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", registry)
        result = _assess_wiring_reads()

        assert result.risk == "red", case
        assert not result.eligible, case
        assert "classification unavailable" in result.red_reasons[0], case


def test_boolean_registry_version_cannot_equal_integer_one(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _registry_payload()
    payload["version"] = True
    registry = _write_registry(tmp_path, payload)
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", registry)

    result = _assess_wiring_reads()

    assert result.risk == "red"
    assert not result.eligible
    assert "classification unavailable" in result.red_reasons[0]


def test_registry_validator_load_failure_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_CHECKER", tmp_path / "missing-checker.py")

    result = _assess_wiring_reads()

    assert result.risk == "red"
    assert not result.eligible
    assert "classification unavailable" in result.red_reasons[0]


def test_ambiguous_quality_classification_fails_closed_red(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _registry_payload()
    payload["surfaces"].append(
        {
            "id": "overlapping-generated-evidence",
            "kind": "generated",
            "paths": ["quality/wiring-reads-baseline.json"],
            "reason": "Test-only overlapping classification must fail closed.",
        }
    )
    registry = _write_registry(tmp_path, payload)
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", registry)

    result = _assess_wiring_reads()

    assert result.risk == "red"
    assert not result.eligible
    assert "ambiguously classified" in result.red_reasons[0]


def test_wiring_reads_migration_left_the_frozen_legacy_set() -> None:
    registry = _registry_payload()
    surface = next(item for item in registry["surfaces"] if item["id"] == "wiring-reads-baseline")

    assert surface["kind"] == "base_derived"
    assert "target_kind" not in surface
    assert "quality/wiring-reads-baseline.json" not in registry["frozen_legacy_paths"]

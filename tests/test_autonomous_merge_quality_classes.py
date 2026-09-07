from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-autonomous-merge.py"
REGISTRY = ROOT / "quality" / "branch-independence.json"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge_quality_classes", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

# ADR-083126-5e62 declares `contracts: [behavioral]`, and ADR-032 says a
# document claiming a kind has a test marked with that kind. This suite is the
# ADR's listed evidence for how generated vs. trusted quality surfaces are
# classified, which is behavioral, so the marker is the claim becoming true
# rather than the ledger absorbing another entry.
pytestmark = [pytest.mark.contract("behavioral")]


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


@pytest.mark.ac("ADR-083126-5e62/AC-1")
@pytest.mark.ac("SPEC-083126-5e62/AC-1")
def test_base_derived_quality_evidence_is_yellow_not_red() -> None:
    result = _assess_wiring_reads()

    assert result.risk == "yellow"
    assert not result.eligible
    assert not result.red_reasons
    assert result.yellow_reasons == [
        "branch-independent quality evidence changed (base_derived): "
        "quality/wiring-reads-baseline.json"
    ]


@pytest.mark.ac("ADR-083126-5e62/AC-1")
@pytest.mark.ac("SPEC-083126-5e62/AC-3")
def test_merge_group_may_carry_base_derived_quality_evidence() -> None:
    result = mod.assess([cf("quality/wiring-reads-baseline.json")], "", merge_group=True)

    assert result.risk == "yellow"
    assert result.eligible


@pytest.mark.ac("ADR-083126-5e62/AC-1")
@pytest.mark.ac("SPEC-083126-5e62/AC-2")
def test_quality_specification_stays_red() -> None:
    result = mod.assess(
        [cf("quality/ratchet-authorizations.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "(specification)" in result.red_reasons[0]


@pytest.mark.ac("ADR-083126-5e62/AC-1")
@pytest.mark.ac("SPEC-083126-5e62/AC-2")
def test_unmigrated_quality_aggregate_stays_red() -> None:
    result = mod.assess(
        [cf("quality/vulture-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "(legacy_shared_aggregate)" in result.red_reasons[0]


@pytest.mark.ac("ADR-083126-5e62/AC-2")
@pytest.mark.ac("SPEC-083126-5e62/AC-2")
def test_unknown_quality_surface_fails_closed_red() -> None:
    result = mod.assess([cf("quality/new-output.json")], "", head_ref="chatgpt/x")

    assert result.risk == "red"
    assert not result.eligible
    assert "unclassified" in result.red_reasons[0]


@pytest.mark.ac("ADR-083126-5e62/AC-2")
@pytest.mark.ac("SPEC-083126-5e62/AC-2")
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


@pytest.mark.ac("ADR-083126-5e62/AC-2")
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
        surface = next(
            item for item in payload["surfaces"] if item["id"] == "wiring-reads-baseline"
        )
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


@pytest.mark.ac("ADR-083126-5e62/AC-2")
@pytest.mark.ac("SPEC-083126-5e62/AC-2")
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


@pytest.mark.ac("SPEC-083126-5e62/AC-4")
def test_wiring_reads_migration_left_the_frozen_legacy_set() -> None:
    registry = _registry_payload()
    surface = next(item for item in registry["surfaces"] if item["id"] == "wiring-reads-baseline")

    assert surface["kind"] == "base_derived"
    assert "target_kind" not in surface
    assert "quality/wiring-reads-baseline.json" not in registry["frozen_legacy_paths"]


# --- Focused coverage of every fail-closed registry-validation branch ---
#
# The pipeline in scripts/check-autonomous-merge.py (_branch_independence_errors
# and _quality_surfaces) turns any unusable checker, validator result, or
# registry shape into ``None`` so _quality_reason fails closed to RED. Each test
# below pins one branch decision; line numbers refer to the script as of this
# change.


class _LoaderlessSpec:
    """Stand-in for a spec importlib may return without a loader attached."""

    loader = None


def _use_registry(monkeypatch, tmp_path: Path, payload: object) -> None:
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", _write_registry(tmp_path, payload))


def _use_checker(monkeypatch, tmp_path: Path, body: str) -> Path:
    checker = tmp_path / "stand-in-checker.py"
    checker.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_CHECKER", checker)
    return checker


def _trust_registry_schema(monkeypatch) -> None:
    # Lines 204, 209 and 213 re-validate structure the canonical validator
    # already rejects; accepting the schema first pins that defense in depth.
    monkeypatch.setattr(mod, "_branch_independence_errors", lambda raw: [])


def test_checker_location_without_loadable_spec_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # A checker suffix with no registered loader makes spec_from_file_location
    # return None (``spec is None`` -> line 166).
    checker = tmp_path / "stand-in-checker.json"
    checker.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_CHECKER", checker)
    _use_registry(monkeypatch, tmp_path, _registry_payload())

    assert mod._quality_surfaces() is None


def test_checker_spec_without_loader_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # A spec whose loader is unset is equally unusable (``spec.loader is
    # None`` -> line 166).
    _use_checker(monkeypatch, tmp_path, "registry_errors = 1\n")
    _use_registry(monkeypatch, tmp_path, _registry_payload())
    monkeypatch.setattr(
        mod.importlib.util, "spec_from_file_location", lambda *args, **kwargs: _LoaderlessSpec()
    )

    assert mod._quality_surfaces() is None


@pytest.mark.parametrize(
    "body",
    [
        "registry_errors = 42\n",
        "# registry_errors intentionally absent\n",
    ],
)
def test_checker_without_callable_validator_fails_closed(
    tmp_path: Path,
    monkeypatch,
    body: str,
) -> None:
    # getattr yields None or a non-callable value (``not callable(validator)``
    # -> line 174).
    _use_checker(monkeypatch, tmp_path, body)
    _use_registry(monkeypatch, tmp_path, _registry_payload())

    assert mod._quality_surfaces() is None


@pytest.mark.parametrize("raised", [KeyError, RuntimeError, TypeError, ValueError])
def test_validator_raising_is_swallowed_to_unclassified(
    tmp_path: Path,
    monkeypatch,
    raised: type[Exception],
) -> None:
    # The guarded validator call converts each guarded exception into no
    # classification (except clause -> lines 177-178).
    body = f"def registry_errors(raw):\n    raise {raised.__name__}('stand-in failure')\n"
    _use_checker(monkeypatch, tmp_path, body)
    _use_registry(monkeypatch, tmp_path, _registry_payload())

    assert mod._quality_surfaces() is None


@pytest.mark.parametrize("returned", [42, None, ["ok", 5]])
def test_validator_bad_result_shape_fails_closed(
    tmp_path: Path,
    monkeypatch,
    returned: object,
) -> None:
    # A non-list result or a list with a non-string member is unusable
    # (``not isinstance(errors, list) or any(...)`` -> line 180).
    body = f"def registry_errors(raw):\n    return {returned!r}\n"
    _use_checker(monkeypatch, tmp_path, body)
    _use_registry(monkeypatch, tmp_path, _registry_payload())

    assert mod._quality_surfaces() is None


def test_registry_top_level_array_fails_closed(tmp_path: Path, monkeypatch) -> None:
    # Valid JSON that is not an object never reaches the validator
    # (``not isinstance(raw, dict)`` -> line 197).
    _use_registry(monkeypatch, tmp_path, ["not", "an", "object"])

    assert mod._quality_surfaces() is None


def test_surfaces_not_a_list_fails_closed(tmp_path: Path, monkeypatch) -> None:
    # ``surfaces`` must be a list (``not isinstance(surfaces, list)`` ->
    # line 204).
    _trust_registry_schema(monkeypatch)
    _use_registry(monkeypatch, tmp_path, {"version": 1, "surfaces": "quality/*"})

    assert mod._quality_surfaces() is None


def test_surface_entry_not_an_object_fails_closed(tmp_path: Path, monkeypatch) -> None:
    # Each surface must be an object (``not isinstance(surface, dict)`` ->
    # line 209).
    _trust_registry_schema(monkeypatch)
    _use_registry(monkeypatch, tmp_path, {"version": 1, "surfaces": ["quality/baseline.json"]})

    assert mod._quality_surfaces() is None


@pytest.mark.parametrize(
    "surface",
    [
        {"kind": 7, "paths": ["quality/x.json"]},
        {"kind": "generated", "paths": "quality/x.json"},
    ],
)
def test_surface_kind_or_paths_wrong_type_fails_closed(
    tmp_path: Path,
    monkeypatch,
    surface: dict,
) -> None:
    # ``kind`` must be a string and ``paths`` a list (``not isinstance(kind,
    # str) or not isinstance(paths, list)`` -> line 213).
    _trust_registry_schema(monkeypatch)
    _use_registry(monkeypatch, tmp_path, {"version": 1, "surfaces": [surface]})

    assert mod._quality_surfaces() is None

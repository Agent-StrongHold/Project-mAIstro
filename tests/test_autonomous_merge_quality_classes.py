from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-autonomous-merge.py"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge_quality_classes", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def cf(path: str, status: str = "M", old_path: str | None = None):
    return mod.ChangedFile(status=status, path=path, old_path=old_path)


def test_base_derived_quality_evidence_is_yellow_not_red() -> None:
    result = mod.assess(
        [cf("quality/wiring-reads-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )

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

    result = mod.assess(
        [cf("quality/wiring-reads-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "classification unavailable" in result.red_reasons[0]


def test_ambiguous_quality_classification_fails_closed_red(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = tmp_path / "branch-independence.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "surfaces": [
                    {
                        "kind": "base_derived",
                        "paths": ["quality/*.json"],
                    },
                    {
                        "kind": "generated",
                        "paths": ["quality/wiring-reads-baseline.json"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "BRANCH_INDEPENDENCE_REGISTRY", registry)

    result = mod.assess(
        [cf("quality/wiring-reads-baseline.json")],
        "",
        head_ref="chatgpt/x",
    )

    assert result.risk == "red"
    assert not result.eligible
    assert "ambiguously classified" in result.red_reasons[0]


def test_wiring_reads_migration_left_the_frozen_legacy_set() -> None:
    registry = json.loads(mod.BRANCH_INDEPENDENCE_REGISTRY.read_text(encoding="utf-8"))
    surface = next(
        item for item in registry["surfaces"] if item["id"] == "wiring-reads-baseline"
    )

    assert surface["kind"] == "base_derived"
    assert "target_kind" not in surface
    assert "quality/wiring-reads-baseline.json" not in registry["frozen_legacy_paths"]

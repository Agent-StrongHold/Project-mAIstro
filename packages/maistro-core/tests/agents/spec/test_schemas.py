"""Coverage for maistro.agents.spec.schemas (was 0%).

Exercises field validation/defaults for every typed agent-output model
and the SCHEMA_REGISTRY + resolve_schema() dotted-path resolution,
including the registry-hit vs. dynamic-import vs. failure branches.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from maistro.agents.spec import schemas
from maistro.agents.spec.schemas import (
    SCHEMA_REGISTRY,
    ArchitectMapping,
    ArchitectNewFile,
    ArchitectOutput,
    CheckpointArchitectureOutput,
    CodeOutput,
    ExtractorOutput,
    FileChange,
    PlanOutput,
    PlanSubtask,
    ReviewOutput,
    ReviewScores,
    ScoutFile,
    ScoutOutput,
    ValidatorCheck,
    ValidatorOutput,
    resolve_schema,
)

# ─── PlanSubtask / PlanOutput ────────────────────────────────────────────────


def test_plan_subtask_defaults() -> None:
    sub = PlanSubtask(id="s1", description="do x")
    assert sub.depends_on == []
    assert sub.agent_role == "coder"


def test_plan_subtask_requires_id_and_description() -> None:
    with pytest.raises(ValidationError):
        PlanSubtask()


def test_plan_output_defaults_and_nested_validation() -> None:
    out = PlanOutput(subtasks=[PlanSubtask(id="s1", description="d")])
    assert out.reasoning == ""
    assert out.estimated_tiers == []
    assert len(out.subtasks) == 1
    assert isinstance(out.subtasks[0], PlanSubtask)


def test_plan_output_requires_subtasks() -> None:
    with pytest.raises(ValidationError):
        PlanOutput()


# ─── FileChange / CodeOutput ─────────────────────────────────────────────────


def test_file_change_defaults() -> None:
    fc = FileChange(path="a.py", action="modify")
    assert fc.description == ""


def test_code_output_defaults() -> None:
    out = CodeOutput()
    assert out.files_modified == []
    assert out.summary == ""
    assert out.tests_added is False


# ─── ReviewScores / ReviewOutput ─────────────────────────────────────────────


def test_review_scores_within_bounds() -> None:
    scores = ReviewScores(correctness=10, quality=0, safety=5.5, completeness=10, overall=0)
    assert scores.correctness == 10
    assert scores.quality == 0


@pytest.mark.parametrize("field", ["correctness", "quality", "safety", "completeness", "overall"])
def test_review_scores_rejects_above_ten(field: str) -> None:
    kwargs = {"correctness": 5, "quality": 5, "safety": 5, "completeness": 5, "overall": 5}
    kwargs[field] = 10.1
    with pytest.raises(ValidationError):
        ReviewScores(**kwargs)


@pytest.mark.parametrize("field", ["correctness", "quality", "safety", "completeness", "overall"])
def test_review_scores_rejects_below_zero(field: str) -> None:
    kwargs = {"correctness": 5, "quality": 5, "safety": 5, "completeness": 5, "overall": 5}
    kwargs[field] = -0.1
    with pytest.raises(ValidationError):
        ReviewScores(**kwargs)


def test_review_output_defaults() -> None:
    scores = ReviewScores(correctness=5, quality=5, safety=5, completeness=5, overall=5)
    out = ReviewOutput(scores=scores)
    assert out.selected_candidate == 0
    assert out.feedback == ""
    assert out.approved is False


def test_review_output_requires_scores() -> None:
    with pytest.raises(ValidationError):
        ReviewOutput()


# ─── ScoutFile / ScoutOutput ─────────────────────────────────────────────────


def test_scout_file_defaults() -> None:
    f = ScoutFile(path="a.py", lines=10)
    assert f.imports == []
    assert f.exports == []
    assert f.category == ""


def test_scout_output_defaults() -> None:
    out = ScoutOutput(files=[ScoutFile(path="a.py", lines=1)])
    assert out.total_lines == 0
    assert out.dependency_graph == {}
    assert out.god_files == []
    assert out.summary == ""


# ─── Architect models ────────────────────────────────────────────────────────


def test_architect_mapping_defaults() -> None:
    m = ArchitectMapping(source="a", target="b")
    assert m.transforms == []
    assert m.priority == 5


def test_architect_new_file_defaults() -> None:
    f = ArchitectNewFile(path="a.py", description="new file")
    assert f.template == ""


def test_architect_output_defaults() -> None:
    out = ArchitectOutput(
        directory_structure=["src/"],
        file_mappings=[ArchitectMapping(source="a", target="b")],
    )
    assert out.new_files == []
    assert out.subtasks == []
    assert out.reasoning == ""


def test_architect_output_requires_directory_structure_and_mappings() -> None:
    with pytest.raises(ValidationError):
        ArchitectOutput()


def test_checkpoint_architecture_output_all_fields_default() -> None:
    out = CheckpointArchitectureOutput()
    assert out.checkpoint_goal == ""
    assert out.allowed_files == []
    assert out.non_goals == []
    assert out.invariants == []
    assert out.review_focus == []
    assert out.test_focus == []
    assert out.summary == ""


# ─── ExtractorOutput / ValidatorOutput ───────────────────────────────────────


def test_extractor_output_all_fields_default() -> None:
    out = ExtractorOutput()
    assert out.files_written == []
    assert out.renames_applied == []
    assert out.sanitizations == []
    assert out.warnings == []
    assert out.summary == ""


def test_validator_check_defaults() -> None:
    check = ValidatorCheck(name="lint", passed=True)
    assert check.output == ""


def test_validator_output_defaults() -> None:
    out = ValidatorOutput(checks=[ValidatorCheck(name="lint", passed=True)], all_passed=True)
    assert out.blocking_issues == []
    assert out.summary == ""


def test_validator_output_requires_checks_and_all_passed() -> None:
    with pytest.raises(ValidationError):
        ValidatorOutput()


# ─── SCHEMA_REGISTRY / resolve_schema() ──────────────────────────────────────


def test_schema_registry_contains_all_expected_dotted_keys() -> None:
    expected_keys = {
        "schemas.PlanSubtask",
        "schemas.PlanOutput",
        "schemas.FileChange",
        "schemas.CodeOutput",
        "schemas.ReviewScores",
        "schemas.ReviewOutput",
        "schemas.ScoutFile",
        "schemas.ScoutOutput",
        "schemas.ArchitectMapping",
        "schemas.ArchitectNewFile",
        "schemas.ArchitectOutput",
        "schemas.CheckpointArchitectureOutput",
        "schemas.ExtractorOutput",
        "schemas.ValidatorCheck",
        "schemas.ValidatorOutput",
    }
    assert set(SCHEMA_REGISTRY.keys()) == expected_keys


def test_resolve_schema_hits_registry_directly() -> None:
    assert resolve_schema("schemas.PlanOutput") is PlanOutput


def test_resolve_schema_dynamic_import_of_module_level_class() -> None:
    # Not in SCHEMA_REGISTRY, but resolvable via importlib since `schemas`
    # exposes BaseModel at module scope (it's imported, but also a BaseModel
    # subclass check passes for `BaseModel` itself).
    result = resolve_schema("pydantic.BaseModel")
    assert result is BaseModel


def test_resolve_schema_dynamic_import_of_this_modules_class() -> None:
    result = resolve_schema("maistro.agents.spec.schemas.FileChange")
    assert result is FileChange


def test_resolve_schema_returns_none_for_unknown_module() -> None:
    assert resolve_schema("totally.made.up.module.Thing") is None


def test_resolve_schema_returns_none_for_class_not_found_in_real_module() -> None:
    assert resolve_schema("maistro.agents.spec.schemas.NotARealClass") is None


def test_resolve_schema_returns_none_for_non_basemodel_target() -> None:
    # `resolve_schema` is itself a real, importable attribute but not a
    # BaseModel subclass -> isinstance/issubclass check fails -> None.
    assert resolve_schema("maistro.agents.spec.schemas.resolve_schema") is None


def test_resolve_schema_returns_none_for_malformed_dotted_path() -> None:
    # No "." to split on -> rsplit raises ValueError, caught internally.
    assert resolve_schema("nodothere") is None


def test_plan_output_and_code_output_were_explicitly_rebuilt() -> None:
    # model_rebuild() calls in source are idempotent no-ops for these simple
    # models (no forward refs to resolve); just confirm the classes are
    # still usable Pydantic models after rebuild.
    assert issubclass(schemas.PlanOutput, BaseModel)
    assert issubclass(schemas.CodeOutput, BaseModel)

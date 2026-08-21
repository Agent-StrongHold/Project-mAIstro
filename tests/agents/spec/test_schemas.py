"""Tests for Pydantic schemas + SCHEMA_REGISTRY (ADR-005)."""

from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

from maistro.agents.spec.schemas import (
    SCHEMA_REGISTRY,
    PlanOutput,
    PlanSubtask,
    ReviewOutput,
    ReviewScores,
    ScoutFile,
    ScoutOutput,
    resolve_schema,
)


class TestImports:
    def test_all_schemas_importable(self) -> None:
        # Verify no circular imports or missing symbols
        from maistro.agents.spec import schemas  # noqa: F401


class TestSchemaRegistry:
    def test_registry_has_expected_keys(self) -> None:
        expected = {
            "schemas.PlanOutput",
            "schemas.CodeOutput",
            "schemas.ReviewOutput",
            "schemas.ScoutOutput",
            "schemas.ArchitectOutput",
            "schemas.ExtractorOutput",
            "schemas.ValidatorOutput",
        }
        assert expected.issubset(set(SCHEMA_REGISTRY.keys()))

    def test_resolve_known_schema(self) -> None:
        cls = resolve_schema("schemas.ScoutOutput")
        assert cls is ScoutOutput

    def test_resolve_unknown_schema_returns_none(self) -> None:
        result = resolve_schema("schemas.DoesNotExist")
        assert result is None

    def test_resolve_unknown_no_exception(self) -> None:
        resolve_schema("totally.bogus.module.ClassName")  # must not raise

    def test_resolve_dynamic_import(self) -> None:
        # Register a custom Pydantic model in a temp module
        from pydantic import BaseModel

        mod = types.ModuleType("_test_dynamic_schema")

        class MySchema(BaseModel):
            value: int

        mod.MySchema = MySchema
        sys.modules["_test_dynamic_schema"] = mod

        try:
            cls = resolve_schema("_test_dynamic_schema.MySchema")
            assert cls is MySchema
        finally:
            del sys.modules["_test_dynamic_schema"]


class TestReviewScores:
    def test_valid_scores(self) -> None:
        scores = ReviewScores(
            correctness=8.0, quality=7.5, safety=9.0, completeness=6.5, overall=7.8
        )
        assert scores.overall == 7.8

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewScores(correctness=-1, quality=5, safety=5, completeness=5, overall=5)

    def test_score_above_ten_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewScores(correctness=11, quality=5, safety=5, completeness=5, overall=5)


class TestRoundtrips:
    def test_plan_output_roundtrip(self) -> None:
        plan = PlanOutput(
            subtasks=[PlanSubtask(id="s1", description="Do X", agent_role="coder")],
            reasoning="Simple",
        )
        restored = PlanOutput.model_validate_json(plan.model_dump_json())
        assert restored.subtasks[0].id == "s1"

    def test_scout_output_roundtrip(self) -> None:
        scout = ScoutOutput(
            files=[ScoutFile(path="src/foo.py", lines=42)],
            total_lines=42,
        )
        restored = ScoutOutput.model_validate_json(scout.model_dump_json())
        assert restored.files[0].path == "src/foo.py"

    def test_review_output_roundtrip(self) -> None:
        review = ReviewOutput(
            scores=ReviewScores(correctness=8, quality=8, safety=9, completeness=7, overall=8),
            approved=True,
        )
        restored = ReviewOutput.model_validate_json(review.model_dump_json())
        assert restored.approved is True

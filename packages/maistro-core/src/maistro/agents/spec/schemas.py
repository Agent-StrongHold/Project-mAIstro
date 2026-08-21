"""Pydantic schemas for typed agent outputs + SCHEMA_REGISTRY (ADR-005)."""

from __future__ import annotations

import importlib

from pydantic import BaseModel, Field

# ── Planner ───────────────────────────────────────────────────────


class PlanSubtask(BaseModel):
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    agent_role: str = "coder"


class PlanOutput(BaseModel):
    subtasks: list[PlanSubtask]
    reasoning: str = ""
    estimated_tiers: list[int] = Field(default_factory=list)


PlanOutput.model_rebuild()


# ── Coder ─────────────────────────────────────────────────────────


class FileChange(BaseModel):
    path: str
    action: str
    description: str = ""


class CodeOutput(BaseModel):
    files_modified: list[FileChange] = Field(default_factory=list)
    summary: str = ""
    tests_added: bool = False


CodeOutput.model_rebuild()


# ── Reviewer ──────────────────────────────────────────────────────


class ReviewScores(BaseModel):
    correctness: float = Field(ge=0, le=10)
    quality: float = Field(ge=0, le=10)
    safety: float = Field(ge=0, le=10)
    completeness: float = Field(ge=0, le=10)
    overall: float = Field(ge=0, le=10)


class ReviewOutput(BaseModel):
    scores: ReviewScores
    selected_candidate: int = 0
    feedback: str = ""
    approved: bool = False


ReviewOutput.model_rebuild()


# ── Scout ─────────────────────────────────────────────────────────


class ScoutFile(BaseModel):
    path: str
    lines: int
    imports: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    category: str = ""


class ScoutOutput(BaseModel):
    files: list[ScoutFile]
    total_lines: int = 0
    dependency_graph: dict[str, list[str]] = Field(default_factory=dict)
    god_files: list[str] = Field(default_factory=list)
    summary: str = ""


ScoutOutput.model_rebuild()


# ── Architect ─────────────────────────────────────────────────────


class ArchitectMapping(BaseModel):
    source: str
    target: str
    transforms: list[str] = Field(default_factory=list)
    priority: int = 5


class ArchitectNewFile(BaseModel):
    path: str
    description: str
    template: str = ""


class ArchitectOutput(BaseModel):
    directory_structure: list[str]
    file_mappings: list[ArchitectMapping]
    new_files: list[ArchitectNewFile] = Field(default_factory=list)
    subtasks: list[str] = Field(default_factory=list)
    reasoning: str = ""


ArchitectOutput.model_rebuild()


class CheckpointArchitectureOutput(BaseModel):
    checkpoint_goal: str = ""
    allowed_files: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    review_focus: list[str] = Field(default_factory=list)
    test_focus: list[str] = Field(default_factory=list)
    summary: str = ""


CheckpointArchitectureOutput.model_rebuild()


# ── Extractor ─────────────────────────────────────────────────────


class ExtractorOutput(BaseModel):
    files_written: list[FileChange] = Field(default_factory=list)
    renames_applied: list[str] = Field(default_factory=list)
    sanitizations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


# ── Validator ─────────────────────────────────────────────────────


class ValidatorCheck(BaseModel):
    name: str
    passed: bool
    output: str = ""


class ValidatorOutput(BaseModel):
    checks: list[ValidatorCheck]
    all_passed: bool
    blocking_issues: list[str] = Field(default_factory=list)
    summary: str = ""


# ── Registry ──────────────────────────────────────────────────────

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "schemas.PlanSubtask": PlanSubtask,
    "schemas.PlanOutput": PlanOutput,
    "schemas.FileChange": FileChange,
    "schemas.CodeOutput": CodeOutput,
    "schemas.ReviewScores": ReviewScores,
    "schemas.ReviewOutput": ReviewOutput,
    "schemas.ScoutFile": ScoutFile,
    "schemas.ScoutOutput": ScoutOutput,
    "schemas.ArchitectMapping": ArchitectMapping,
    "schemas.ArchitectNewFile": ArchitectNewFile,
    "schemas.ArchitectOutput": ArchitectOutput,
    "schemas.CheckpointArchitectureOutput": CheckpointArchitectureOutput,
    "schemas.ExtractorOutput": ExtractorOutput,
    "schemas.ValidatorCheck": ValidatorCheck,
    "schemas.ValidatorOutput": ValidatorOutput,
}


def resolve_schema(dotted_path: str) -> type[BaseModel] | None:
    """Resolve a dotted path to a Pydantic model class."""
    if dotted_path in SCHEMA_REGISTRY:
        return SCHEMA_REGISTRY[dotted_path]
    try:
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            return cls
    except (ImportError, AttributeError, ValueError):
        pass
    return None

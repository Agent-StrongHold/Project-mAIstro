"""Persona template schema (ADR-060 §2, SPEC-192 P1).

A persona template is one YAML file under a unified ``templates/`` root with a
``kind:`` discriminator (SPEC-192 open question 1 — DECIDED):

- ``kind: department`` — eval rubric only (replaces Python department files).
- ``kind: author`` / ``kind: creator`` — voice + eval rubric + ``spawns:`` block.
- ``kind: workspace`` — a persona a user adopts as a live Hive Conductor
  workspace tab (e.g. "PM Fleet"): voice + eval rubric + ``spawns:`` (same
  shape as author/creator) plus ``brand`` and ``ui_scope``, since a workspace
  persona's identity is its brand, its voice, its relevant tools, and its
  scoped UI, not just a content-generation voice.

Department YAML files that predate the ``kind:`` field (bare ``department:`` +
``evals:``) are accepted and normalised to ``kind: department``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CriterionSpec(BaseModel):
    """One weighted criterion inside an eval dimension."""

    name: str
    weight: int
    check: dict[str, Any]
    evidence: list[str] = Field(default_factory=list)  # source URLs (Tier 1 grounding)


class EvalSpec(BaseModel):
    """One eval dimension: a named, weighted rubric."""

    name: str
    tier: int = 1
    criteria: list[CriterionSpec] = Field(default_factory=list)


class VoiceSpec(BaseModel):
    """Persona voice specification (author/creator kinds)."""

    archetype: str = ""
    audience: str = ""
    tone: str = ""
    rules: list[str] = Field(default_factory=list)
    example: str = ""


class SpawnSpec(BaseModel):
    """One agent declaration in a persona's ``spawns:`` block (maps onto AgentRecipe)."""

    agent: str
    role: str = ""  # human description → AgentRecipe.description
    reasoning_strategy: str = "direct"
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    inherits_voice: bool = True
    scored_by: list[str] = Field(default_factory=list)
    hard_gates: list[str] = Field(default_factory=list)


class BrandSpec(BaseModel):
    """A ``kind: workspace`` persona's product identity (workspace tab label/copy)."""

    display_name: str = ""
    tagline: str = ""
    icon: str = ""


class InterviewQuestionSpec(BaseModel):
    """One question in a ``kind: workspace`` persona's own onboarding
    interview script (``maistro.agents.program_context``). ``field`` names
    matching a known ``ProgramContext`` attribute (``program_name``,
    ``goals``, ``tools``, ``constraints``, ``stakeholders``) get typed
    capture there; any other name is still recorded, just as a freeform
    fact rather than a typed field. Optional -- a persona with no
    ``interview:`` block falls back to the generic 4-question script,
    exactly as before this field existed."""

    field: str
    agent: str = "intake"
    question: str


class PersonaTemplate(BaseModel):
    """A full persona/department template loaded from one YAML file."""

    kind: Literal["department", "author", "creator", "workspace"] = "department"
    id: str
    business_model: str = ""
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    evals: list[EvalSpec] = Field(default_factory=list)
    spawns: list[SpawnSpec] = Field(default_factory=list)
    # `kind: workspace` only: workspace tab brand + the persona's declared nav
    # scope (which pages/nav items are relevant when this persona is active).
    brand: BrandSpec = Field(default_factory=BrandSpec)
    ui_scope: list[str] = Field(default_factory=list)
    # `kind: workspace` only: this persona's own onboarding interview script.
    # Empty means "no custom script" -- callers fall back to the generic one.
    interview: list[InterviewQuestionSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_department_shape(cls, data: Any) -> Any:
        """Normalise legacy department YAML (``department:`` key, no ``kind``)."""
        if isinstance(data, dict) and "id" not in data and "department" in data:
            data = dict(data)
            data["id"] = data.pop("department")
            data.setdefault("kind", "department")
        return data

    @model_validator(mode="after")
    def _validate_bindings(self) -> PersonaTemplate:
        eval_names = {e.name for e in self.evals}
        criterion_names = {c.name for e in self.evals for c in e.criteria}
        for spawn in self.spawns:
            unknown_evals = set(spawn.scored_by) - eval_names
            if unknown_evals:
                raise ValueError(
                    f"spawn {spawn.agent!r}: scored_by references unknown evals {sorted(unknown_evals)}"
                )
            unknown_gates = set(spawn.hard_gates) - criterion_names
            if unknown_gates:
                raise ValueError(
                    f"spawn {spawn.agent!r}: hard_gates references unknown criteria {sorted(unknown_gates)}"
                )
        return self

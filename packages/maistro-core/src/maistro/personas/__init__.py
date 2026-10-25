"""Persona authoring and live product-context domain."""

from __future__ import annotations

from maistro.personas.checklist import (
    CapabilityItem,
    capability_checklist,
    default_checklist_ids,
)
from maistro.personas.expander import ExpandedAgent, ExpandedPersona, expand_persona
from maistro.personas.golden import (
    EvidencedCriterion,
    GoldenRecord,
    GoldenRecordDiff,
    GoldenRecordStore,
    InMemoryGoldenRecordStore,
    SourceEvidence,
)
from maistro.personas.model import Persona, PersonaSurface
from maistro.personas.rubric import EvalResult, RubricEval, load_evals, load_templates
from maistro.personas.schema import (
    BrandSpec,
    CriterionSpec,
    EvalSpec,
    PersonaTemplate,
    PersonaTemplateSource,
    SpawnSpec,
    VoiceSpec,
)
from maistro.personas.scorer import DeepEvalScorer, RubricScorer, create_judge_scorer
from maistro.personas.store import (
    InMemoryPersonaStore,
    PersonaAlreadyExists,
    PersonaNotFound,
    PersonaStore,
    WorkspacePersonaAlreadyExists,
)

__all__ = [
    "BrandSpec",
    "CapabilityItem",
    "CriterionSpec",
    "DeepEvalScorer",
    "EvalResult",
    "EvalSpec",
    "EvidencedCriterion",
    "ExpandedAgent",
    "ExpandedPersona",
    "GoldenRecord",
    "GoldenRecordDiff",
    "GoldenRecordStore",
    "InMemoryGoldenRecordStore",
    "InMemoryPersonaStore",
    "Persona",
    "PersonaAlreadyExists",
    "PersonaNotFound",
    "PersonaStore",
    "PersonaSurface",
    "PersonaTemplate",
    "PersonaTemplateSource",
    "RubricEval",
    "RubricScorer",
    "SourceEvidence",
    "SpawnSpec",
    "VoiceSpec",
    "WorkspacePersonaAlreadyExists",
    "capability_checklist",
    "create_judge_scorer",
    "default_checklist_ids",
    "expand_persona",
    "load_evals",
    "load_templates",
]

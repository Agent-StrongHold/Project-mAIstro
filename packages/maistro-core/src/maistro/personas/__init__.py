"""Persona authoring and live product-context domain."""

from __future__ import annotations

import importlib
from typing import Any

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
from maistro.personas.store import (
    InMemoryPersonaStore,
    PersonaAlreadyExists,
    PersonaNotFound,
    PersonaStore,
    WorkspacePersonaAlreadyExists,
)
from maistro.personas.wiring import PERSONA_PG_TABLES, wire_persona_store

#: The scorer tier loads lazily (#552): importing ``maistro.personas`` must not
#: drag the scorer's judge dependencies onto every persona consumer, and the
#: RSI promotion path (#552 canonical convergence) reaches this package through
#: the Workspace persona store, so the facade keeps its static import graph to
#: the data/store tier. Same contract as ``maistro.identity``: the names stay
#: importable from the package root, the module loads on first access.
_SCORER_NAMES = frozenset({"DeepEvalScorer", "RubricScorer", "create_judge_scorer"})


def __getattr__(name: str) -> Any:
    """Load :mod:`maistro.personas.scorer` only when one of its names is used."""

    if name in _SCORER_NAMES:
        scorer = importlib.import_module("maistro.personas.scorer")
        return getattr(scorer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "PERSONA_PG_TABLES",
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
    "wire_persona_store",
]

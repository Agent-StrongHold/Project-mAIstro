"""Maistro Turing — autonoetic self-model extensions for the Maistro platform."""

from __future__ import annotations

import importlib.metadata

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-turing")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"

from maistro_turing.bridge import (
    TuringClassifierBridge,
    TuringMemoryBridge,
    TuringProviderBridge,
    TuringSecurityBridge,
)
from maistro_turing.cognition.reactor import (
    FakeReactor,
    IntervalTrigger,
    Reactor,
)
from maistro_turing.protocols import (
    ImmutableViolation,
    MemoryRepo,
    ProvenanceViolation,
    RepoError,
    WisdomDeferred,
    WisdomInvariantViolation,
    WorkingMemoryStore,
)
from maistro_turing.self_model import (
    ALL_FACETS,
    CANONICAL_FACETS,
    FACET_TO_TRAIT,
    ContributorOrigin,
    Hobby,
    Interest,
    Mood,
    NodeKind,
    Passion,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    PersonalityRevision,
    Preference,
    PreferenceKind,
    SelfTodo,
    SelfTodoRevision,
    Skill,
    SkillKind,
    TodoStatus,
    Trait,
    current_level,
    facet_node_id,
    guess_node_kind,
)
from maistro_turing.tiers import (
    INHERITANCE_PRIORITY,
    WEIGHT_BOUNDS,
    clamp_weight,
)
from maistro_turing.types import (
    DURABLE_TIERS,
    EpisodicMemory,
    MemoryTier,
    SourceKind,
)

__all__ = [
    "ALL_FACETS",
    "CANONICAL_FACETS",
    "DURABLE_TIERS",
    "FACET_TO_TRAIT",
    "IMMUTABLE_FIELDS",
    "INHERITANCE_PRIORITY",
    "WEIGHT_BOUNDS",
    "ContributorOrigin",
    "EpisodicMemory",
    "FakeReactor",
    "Hobby",
    "ImmutableViolation",
    "Interest",
    "IntervalTrigger",
    "MemoryRepo",
    "MemoryTier",
    "Mood",
    "NodeKind",
    "Passion",
    "PersonalityAnswer",
    "PersonalityFacet",
    "PersonalityItem",
    "PersonalityRevision",
    "Preference",
    "PreferenceKind",
    "ProvenanceViolation",
    "Reactor",
    "RepoError",
    "SelfTodo",
    "SelfTodoRevision",
    "Skill",
    "SkillKind",
    "SourceKind",
    "TodoStatus",
    "Trait",
    "TuringClassifierBridge",
    "TuringMemoryBridge",
    "TuringProviderBridge",
    "TuringSecurityBridge",
    "WisdomDeferred",
    "WisdomInvariantViolation",
    "WorkingMemoryStore",
    "__version__",
    "clamp_weight",
    "current_level",
    "facet_node_id",
    "guess_node_kind",
]

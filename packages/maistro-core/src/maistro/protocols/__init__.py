"""Protocol contracts for maistro-engine dependency injection."""

from __future__ import annotations

from maistro.protocols.agents import AgentStore
from maistro.protocols.auth import AuthProvider
from maistro.protocols.classifier import IntentClassifier
from maistro.protocols.codebase import CodeStructureIndex
from maistro.protocols.embeddings import EmbeddingClient
from maistro.protocols.feedback import FeedbackExtractor, ViolationStore
from maistro.protocols.llm import LLMClient
from maistro.protocols.memory import (
    AuditLog,
    DecayableEpisodicStore,
    EpisodicStore,
    LearningExtractor,
    LearningStore,
    OutcomeStore,
    RCAExtractor,
    SessionStore,
    SkillMutationStore,
)
from maistro.protocols.notification import Notification, NotificationClient
from maistro.protocols.prompts import PromptManager
from maistro.protocols.quota import QuotaTracker
from maistro.protocols.router import ModelRouter
from maistro.protocols.scorer import Score, Scorer
from maistro.protocols.secrets import SecretBackend, SecretResult
from maistro.protocols.skills import SkillForge, SkillLoader, SkillMarketplace
from maistro.protocols.spec import SpecStore, SpecVerifier
from maistro.protocols.tools import ToolExecutor, ToolPlugin, ToolRegistry
from maistro.protocols.tracing import Span, Trace, TracingBackend

__all__ = [
    "AgentStore",
    "AuditLog",
    "AuthProvider",
    "CodeStructureIndex",
    "DecayableEpisodicStore",
    "EmbeddingClient",
    "EpisodicStore",
    "FeedbackExtractor",
    "IntentClassifier",
    "LLMClient",
    "LearningExtractor",
    "LearningStore",
    "ModelRouter",
    "Notification",
    "NotificationClient",
    "OutcomeStore",
    "PromptManager",
    "QuotaTracker",
    "RCAExtractor",
    "Score",
    "Scorer",
    "SecretBackend",
    "SecretResult",
    "SessionStore",
    "SkillForge",
    "SkillLoader",
    "SkillMarketplace",
    "SkillMutationStore",
    "Span",
    "SpecStore",
    "SpecVerifier",
    "ToolExecutor",
    "ToolPlugin",
    "ToolRegistry",
    "Trace",
    "TracingBackend",
    "ViolationStore",
]

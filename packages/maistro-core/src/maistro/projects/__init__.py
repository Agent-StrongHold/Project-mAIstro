"""Project package during convergence from legacy ownership to canonical scope.

Project is canonical beneath Workspace as a nested organization, configuration,
authorization, and resource scope. The canonical model and stores live in
:mod:`maistro.projects.scope`, :mod:`maistro.projects.scope_store`, and
:mod:`maistro.projects.sqlite_scope_store`.

The older-ownership exports in this module are the legacy ownership-root Project
API. They remain reachable during caller migration and must not be mistaken for
the canonical Project scope model or used as a new Workspace alias.

The Goal `Rubric` store exports (M7-A2, issue #791) are *not* legacy: they are
the package's public persistence surface for the Rubric scored-acceptance
object, exported beside ``InMemoryProjectStore`` like every Project-scoped
store. Consumers score Runs and gate fences against it in later M7 work; the
classification lives in :mod:`maistro.projects.rubric_store`.
"""

from __future__ import annotations

from .domains import KNOWN_DOMAINS, DomainConfig, domain_for, domain_use_cases
from .rubric_store import (
    GoalRevisionCatalog,
    GoalRevisionSnapshot,
    RubricError,
    RubricGoalNotLiveError,
    RubricNotFoundError,
    RubricRevisionConflictError,
    RubricRunBinding,
    RubricRunBindingConflictError,
    RubricScopeMismatchError,
    RubricStore,
)
from .store import InMemoryProjectStore, ProjectStore
from .types import (
    AirtableResourceBinding,
    JiraResourceBinding,
    Project,
    ProjectAccessDenied,
    ProjectMember,
    ProjectMemberRole,
    ProjectNotFound,
    ProjectQuotaExceeded,
    ProjectSettings,
    RepoResourceBinding,
)

__all__ = [
    "KNOWN_DOMAINS",
    "AirtableResourceBinding",
    "DomainConfig",
    "GoalRevisionCatalog",
    "GoalRevisionSnapshot",
    "InMemoryProjectStore",
    "JiraResourceBinding",
    "Project",
    "ProjectAccessDenied",
    "ProjectMember",
    "ProjectMemberRole",
    "ProjectNotFound",
    "ProjectQuotaExceeded",
    "ProjectSettings",
    "ProjectStore",
    "RepoResourceBinding",
    "RubricError",
    "RubricGoalNotLiveError",
    "RubricNotFoundError",
    "RubricRevisionConflictError",
    "RubricRunBinding",
    "RubricRunBindingConflictError",
    "RubricScopeMismatchError",
    "RubricStore",
    "domain_for",
    "domain_use_cases",
]

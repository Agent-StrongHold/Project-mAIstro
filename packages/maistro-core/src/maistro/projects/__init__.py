"""Project package during convergence from legacy ownership to canonical scope.

Project is canonical beneath Workspace as a nested organization, configuration,
authorization, and resource scope. The canonical model and stores live in
:mod:`maistro.projects.scope`, :mod:`maistro.projects.scope_store`, and
:mod:`maistro.projects.sqlite_scope_store`.

The exports in this module are the older ownership-root Project API. They remain
reachable during caller migration and must not be mistaken for the canonical
Project scope model or used as a new Workspace alias.
"""

from __future__ import annotations

from .domains import KNOWN_DOMAINS, DomainConfig, domain_for, domain_use_cases
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
    "domain_for",
    "domain_use_cases",
]

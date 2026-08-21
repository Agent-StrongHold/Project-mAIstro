"""Service key auth types: scopes, categories, service identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ScopeCategory(StrEnum):
    """Broad permission groups. Granting a category grants all its sub-scopes."""

    LLM = "llm"
    BUILDERS = "builders"
    TRADING = "trading"
    MEMORY = "memory"
    TASKS = "tasks"
    SKILLS = "skills"
    CANVAS = "canvas"
    EVENTS = "events"
    ADMIN = "admin"
    INFRA = "infra"
    HA = "ha"
    TURING = "turing"


class Scope(StrEnum):
    """Individual permissions. Assigned directly or inherited from category."""

    # LLM
    CHAT_COMPLETIONS = "llm:chat_completions"
    MODELS_LIST = "llm:models_list"
    EMBEDDINGS = "llm:embeddings"
    IMAGE_GENERATE = "llm:image_generate"
    RESPONSES_CREATE = "llm:responses_create"
    RESPONSES_READ = "llm:responses_read"
    # BUILDERS
    BUILDERS_ASSIGN = "builders:assign"
    BUILDERS_REVIEW = "builders:review"
    BUILDERS_QUEUE = "builders:queue"
    BUILDERS_SCAN = "builders:scan"
    # TRADING
    TRADING_READ = "trading:read"
    TRADING_WRITE = "trading:write"
    TRADING_PATTERNS = "trading:patterns"
    TRADING_SYSTEM = "trading:system"
    AGENTS_EVOLVE = "trading:evolve"
    # MEMORY
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    # TASKS
    TASKS_READ = "tasks:read"
    TASKS_WRITE = "tasks:write"
    SCHEDULES_MANAGE = "tasks:schedules"
    # SKILLS
    SKILLS_READ = "skills:read"
    SKILLS_WRITE = "skills:write"
    MARKETPLACE = "skills:marketplace"
    # CANVAS
    CANVAS_READ = "canvas:read"
    CANVAS_WRITE = "canvas:write"
    # EVENTS
    EVENTS_EMIT = "events:emit"
    EVENTS_SUBSCRIBE = "events:subscribe"
    EVENTS_HISTORY = "events:history"
    # ADMIN
    ADMIN = "admin:admin"
    TRACES_READ = "admin:traces"
    DASHBOARD = "admin:dashboard"
    # INFRA
    INFRA_READ = "infra:read"
    INFRA_ACTION = "infra:action"
    # HA
    HA_READ = "ha:read"
    HA_WRITE = "ha:write"
    # TURING
    TURING_CHAT = "turing:chat"
    TURING_VAULT_READ = "turing:vault_read"
    TURING_VAULT_WRITE = "turing:vault_write"


CATEGORY_SCOPES: dict[ScopeCategory, frozenset[Scope]] = {
    ScopeCategory.LLM: frozenset(
        {
            Scope.CHAT_COMPLETIONS,
            Scope.MODELS_LIST,
            Scope.EMBEDDINGS,
            Scope.IMAGE_GENERATE,
            Scope.RESPONSES_CREATE,
            Scope.RESPONSES_READ,
        }
    ),
    ScopeCategory.BUILDERS: frozenset(
        {
            Scope.BUILDERS_ASSIGN,
            Scope.BUILDERS_REVIEW,
            Scope.BUILDERS_QUEUE,
            Scope.BUILDERS_SCAN,
        }
    ),
    ScopeCategory.TRADING: frozenset(
        {
            Scope.TRADING_READ,
            Scope.TRADING_WRITE,
            Scope.TRADING_PATTERNS,
            Scope.TRADING_SYSTEM,
            Scope.AGENTS_EVOLVE,
        }
    ),
    ScopeCategory.MEMORY: frozenset(
        {
            Scope.MEMORY_READ,
            Scope.MEMORY_WRITE,
        }
    ),
    ScopeCategory.TASKS: frozenset(
        {
            Scope.TASKS_READ,
            Scope.TASKS_WRITE,
            Scope.SCHEDULES_MANAGE,
        }
    ),
    ScopeCategory.SKILLS: frozenset(
        {
            Scope.SKILLS_READ,
            Scope.SKILLS_WRITE,
            Scope.MARKETPLACE,
        }
    ),
    ScopeCategory.CANVAS: frozenset(
        {
            Scope.CANVAS_READ,
            Scope.CANVAS_WRITE,
        }
    ),
    ScopeCategory.EVENTS: frozenset(
        {
            Scope.EVENTS_EMIT,
            Scope.EVENTS_SUBSCRIBE,
            Scope.EVENTS_HISTORY,
        }
    ),
    ScopeCategory.ADMIN: frozenset(
        {
            Scope.ADMIN,
            Scope.TRACES_READ,
            Scope.DASHBOARD,
        }
    ),
    ScopeCategory.INFRA: frozenset(
        {
            Scope.INFRA_READ,
            Scope.INFRA_ACTION,
        }
    ),
    ScopeCategory.HA: frozenset(
        {
            Scope.HA_READ,
            Scope.HA_WRITE,
        }
    ),
    ScopeCategory.TURING: frozenset(
        {
            Scope.TURING_CHAT,
            Scope.TURING_VAULT_READ,
            Scope.TURING_VAULT_WRITE,
        }
    ),
}

_WILDCARD = "*"


def expand_scopes(raw: list[str]) -> frozenset[Scope]:
    """Expand a list of scope specifiers to concrete Scope values.

    Accepts:
      - "category:*" → all scopes in that category
      - "category:subscope" → single scope (e.g. "llm:chat_completions")
      - "*:*" → all scopes (superuser)
    """
    result: set[Scope] = set()
    for spec in raw:
        if spec == "*:*":
            all_scopes: set[Scope] = set()
            for s in CATEGORY_SCOPES.values():
                all_scopes |= s
            return frozenset(all_scopes)

        if spec.endswith(f":{_WILDCARD}"):
            cat_name = spec[: -len(f":{_WILDCARD}")]
            try:
                cat = ScopeCategory(cat_name)
            except ValueError:
                continue
            result |= CATEGORY_SCOPES[cat]
        else:
            try:
                result.add(Scope(spec))
            except ValueError:
                continue
    return frozenset(result)


@dataclass(frozen=True)
class ServiceIdentity:
    """Authenticated service context — the b2b equivalent of AuthContext."""

    name: str
    key_hash: str = ""
    scopes: frozenset[Scope] = field(default_factory=frozenset)

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes

    def has_any_scope(self, *scopes: Scope) -> bool:
        return bool(self.scopes & frozenset(scopes))

"""Provider registry / routing errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.types.errors import AgentError

if TYPE_CHECKING:
    from maistro.providers.types import RouterBudget


class ProviderError(AgentError):
    """Base class for provider registry / routing errors."""


class ModelNotFoundError(ProviderError):
    """Requested model name is not registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"model not found in registry: {name!r}", code="model_not_found")


class NoEligibleModelError(ProviderError):
    """No registered model satisfies the routing budget constraints."""

    def __init__(self, budget: RouterBudget | None = None, detail: str = "") -> None:
        self.budget = budget
        msg = detail or f"no eligible model for budget: {budget}"
        super().__init__(msg, code="no_eligible_model")


class ProviderConfigError(ProviderError):
    """Provider YAML config is malformed."""

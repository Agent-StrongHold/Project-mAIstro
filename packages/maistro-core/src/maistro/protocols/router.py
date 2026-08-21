"""Model router protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.types.config import RoutingConfig
    from maistro.types.intent import Intent
    from maistro.types.model import ModelConfig, ModelSelection, ProviderConfig


@runtime_checkable
class ModelRouter(Protocol):
    """Selects the optimal model for a classified intent."""

    def select(
        self,
        intent: Intent,
        models: dict[str, ModelConfig],
        providers: dict[str, ProviderConfig],
        routing_config: RoutingConfig,
    ) -> ModelSelection:
        """Select the best model. Raises RoutingError if no models match."""
        ...

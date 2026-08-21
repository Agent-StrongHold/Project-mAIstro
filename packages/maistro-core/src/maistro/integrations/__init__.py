"""Integrations: adapters for external services on the unified platform.

Single-tenant: shared secrets, no inter-service auth.
Each integration knows how to talk to its service and emit/listen for events.
"""

from maistro.integrations.coinswarm import CoinSwarmIntegration
from maistro.integrations.home_assistant import HomeAssistantIntegration
from maistro.integrations.ntfy import NtfyClient
from maistro.integrations.turing import TuringIntegration

__all__ = [
    "CoinSwarmIntegration",
    "HomeAssistantIntegration",
    "NtfyClient",
    "TuringIntegration",
]

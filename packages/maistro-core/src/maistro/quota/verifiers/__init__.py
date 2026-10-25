"""Provider-specific ``QuotaVerifier`` implementations (#2318).

Only providers that expose a real balance/usage endpoint get one here — most
of the roster doesn't (see ``reconciliation.py``) and reconciles ambiently via
response headers/body instead.

The Invocation terminalization path selects an OpenRouter key verifier when
``OPENROUTER_API_KEY`` is set. Mistral's Admin verifier stays schema-gated
(#1205): this package exports the schema contract type so the module is
process-reachable without calling an unconfirmed Admin API shape.
"""

from __future__ import annotations

from maistro.quota.verifiers.mistral import (
    MistralAdminApiVerifier,
    MistralRateLimitSchema,
    MistralSchemaContractError,
)
from maistro.quota.verifiers.openrouter import (
    FREE_MODEL_RPD_NO_CREDITS,
    FREE_MODEL_RPD_WITH_CREDITS,
    OpenRouterActivityVerifier,
    OpenRouterKeyVerifier,
)

#: Schema contract type for Mistral Admin rate-limit replies. Instantiating a
#: verifier still requires a confirmed ``version`` / ``remaining_field`` pair
#: (#1205); exporting the type keeps the module on the Invocation path without
#: guessing field names.
MISTRAL_SCHEMA_CONTRACT = MistralRateLimitSchema
#: Admin verifier class — callable only with a confirmed schema (#1205).
MISTRAL_ADMIN_VERIFIER = MistralAdminApiVerifier

__all__ = [
    "FREE_MODEL_RPD_NO_CREDITS",
    "FREE_MODEL_RPD_WITH_CREDITS",
    "MISTRAL_ADMIN_VERIFIER",
    "MISTRAL_SCHEMA_CONTRACT",
    "MistralAdminApiVerifier",
    "MistralRateLimitSchema",
    "MistralSchemaContractError",
    "OpenRouterActivityVerifier",
    "OpenRouterKeyVerifier",
]

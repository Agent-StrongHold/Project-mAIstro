from __future__ import annotations

from maistro.testing.faux_provider import FauxProvider, FauxResponse, ToolCallDef
from maistro.testing.harness import HarnessEnvironment, create_test_environment

#: Stable principal for tests that do not care which actor admitted the Run.
DEFAULT_TEST_ACTOR_PRINCIPAL_ID = "test-actor-principal"

__all__ = [
    "DEFAULT_TEST_ACTOR_PRINCIPAL_ID",
    "FauxProvider",
    "FauxResponse",
    "HarnessEnvironment",
    "ToolCallDef",
    "create_test_environment",
]

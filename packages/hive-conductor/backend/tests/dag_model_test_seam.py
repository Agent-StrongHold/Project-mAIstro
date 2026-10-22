"""Explicit TEST-only admitted-call substitution for DAG orchestration tests.

These tests exercise traversal, deadlines or transports, not admission policy.
Production dispatch remains fail-closed; only tests that call this installer
replace its admitted-call boundary. Authority/egress tests use real composition.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.capabilities.providers.llm_gateway import ModelChatRequest


def install_test_admitted_model(
    monkeypatch: pytest.MonkeyPatch,
    model_call: Callable[..., Awaitable[str]],
) -> None:
    from services import canonical_dag_runner as runner

    class _TestAdmittedCalls:
        async def complete(
            self,
            *,
            request: ModelChatRequest,
            identity: tuple[str, str, str],
            binding_id: str,
            effect_key: str,
            timeout_s: float,
        ) -> Any:
            assert effect_key == "dag:model"
            assert request.temperature == 0.3
            assert request.response_format == {"type": "json_object"}
            assert timeout_s > 0
            content = await model_call(request.messages, model=request.model)
            return SimpleNamespace(body={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(runner, "dag_node_model_calls", lambda _container: _TestAdmittedCalls())

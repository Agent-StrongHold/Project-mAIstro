"""Core-owned setup/probe security proofs for CI's core-only coverage producer.

Exercise AdmittedModelCalls through real canonical records, Binding/credential
and Invocation services and SQLite request quotas. Only terminal HTTP is a
MockTransport; no model egress helper or authority is mocked.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    Invocation,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.model_chat import ModelCallResult, ModelSetupError
from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    LlmAuthError,
    LlmHttpError,
    ModelChatRequest,
    register_provider_models,
)
from maistro.http import override_transport
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.quota.invocation_quota import InvocationQuotaDenied, QuotaBudget, QuotaEstimate
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

from .test_admitted_model_calls import Setup as AdmittedSetup
from .test_admitted_model_calls import setup as admitted_setup

_SECRET = "fixture-provider-secret-not-for-evidence"
_ADMIN = "fixture-admin-key"
_MODEL = "request-alias"
_EFFECT = "provider.health:core-fixture"


@dataclass
class Setup:
    admitted: AdmittedSetup
    effects: CapabilityEffectContext
    calls: AdmittedModelCalls
    quota: SqliteInvocationQuota
    quota_path: Path
    endpoint: GatewayEndpoint

    async def prepare(self) -> None:
        # The real registration transport is internal to this admitted Invocation.
        # A completed first registration cannot make a partial setup retry-safe.
        await register_provider_models(
            self.endpoint, models=(_MODEL, "second-fixed-model"), api_key=_SECRET
        )

    async def complete(self, setup: Callable[[], Awaitable[None]] | None = None) -> ModelCallResult:
        return await self.calls.complete(
            identity=self.admitted.identity,
            binding_id="declared",
            effect_key=_EFFECT,
            request=ModelChatRequest(
                model=_MODEL, messages=[{"role": "user", "content": "ping"}], max_tokens=1
            ),
            setup=setup or self.prepare,
        )

    async def rows(self) -> list[Invocation]:
        run_id, node_run_id, _attempt_id = self.admitted.identity
        return await self.effects.invocation_store.list_effect(
            run_id=run_id, node_run_id=node_run_id, binding_id="declared", effect_key=_EFFECT
        )

    def stats(self) -> Any:
        return self.effects.credentials.stats(
            workspace_id="workspace", project_id=self.admitted.project_id, provider="litellm"
        )

    def quota_evidence(self) -> str:
        with sqlite3.connect(self.quota_path) as database:
            return "\n".join(database.iterdump())


async def _setup(tmp_path: Path, *, limit: int = 1) -> Setup:
    admitted = await admitted_setup()

    async def estimate(invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        run = await admitted.runs.get_run(invocation.run_id)
        assert run is not None
        assert invocation.actor_id == run.actor_principal_id
        return QuotaEstimate(principal_id=run.actor_principal_id)

    path = tmp_path / "setup-quota.sqlite3"
    quota = SqliteInvocationQuota(path, estimate=estimate)
    await quota.ensure_schema()
    await quota.register_budget(
        QuotaBudget(
            budget_id="one-setup-probe",
            unit="requests",
            limit=limit,
            period_start=0,
            period_end=2**62,
            coverage_ref="fixture-opening",
            opening_spend=0,
            workspace_id="workspace",
            principal_id="admitted-actor",
            capability="model.chat",
        )
    )
    effects = new_in_memory_effect_context(
        binding_store=admitted.effects.bindings,
        credentials=admitted.effects.credentials,
        policy_evaluator=binding_scope_policy,
        quota=quota,
    )
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name=_MODEL,
                provider="fixture",
                cost_per_1k_input=1.0,
                cost_per_1k_output=1.0,
                latency_p50_ms=1,
            )
        ]
    )
    endpoint = GatewayEndpoint(base_url="https://gateway.invalid", api_key=_ADMIN)
    calls = AdmittedModelCalls(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=endpoint,
        run_store=admitted.runs,
        binding_ids=("declared",),
    )
    return Setup(admitted, effects, calls, quota, path, endpoint)


def _ok() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "fixture-version",
            "choices": [{"message": {"content": "pong"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    )


async def _assert_unknown_without_secret(s: Setup, caplog: pytest.LogCaptureFixture) -> Invocation:
    (row,) = await s.rows()
    assert row.status is InvocationStatus.UNKNOWN
    assert row.actor_id == "admitted-actor" and row.attempt_id == s.admitted.identity[2]
    balance = await s.quota.balance("one-setup-probe")
    assert balance.held == 1 and balance.spent == 0
    assert _SECRET not in row.model_dump_json() + s.quota_evidence() + caplog.text
    assert _ADMIN not in row.model_dump_json() + s.quota_evidence() + caplog.text
    return row


async def test_setup_follows_quota_and_uses_admin_while_probe_uses_scoped_key(
    tmp_path: Path,
) -> None:
    s = await _setup(tmp_path)
    sent: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        (row,) = await s.rows()
        assert row.status is InvocationStatus.RUNNING
        assert (await s.quota.balance("one-setup-probe")).held == 1
        if request.url.path == "/model/new":
            assert request.headers["Authorization"] == f"Bearer {_ADMIN}"
            assert json.loads(request.content)["litellm_params"]["api_key"] == _SECRET
        else:
            assert request.headers["Authorization"] == "Bearer fixture-key"
            assert json.loads(request.content)["max_tokens"] == 1
        return _ok()

    with override_transport(httpx.MockTransport(respond)):
        first = await s.complete()
        replay = await s.complete()
    assert first.invocation_id == replay.invocation_id
    assert [request.url.path for request in sent] == [
        "/model/new",
        "/model/new",
        "/v1/chat/completions",
    ]
    assert (await s.rows())[0].status is InvocationStatus.COMPLETED
    balance = await s.quota.balance("one-setup-probe")
    assert balance.spent == 1 and balance.held == 0
    assert s.stats().total_use_count == 1


@pytest.mark.parametrize(
    "failure", ["admin-status", "typed-auth", "partial", "transport", "callback"]
)
async def test_setup_failure_sanitizes_context_without_charging_probe_health(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    s = await _setup(tmp_path)
    caplog.set_level("DEBUG")
    sent: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        assert request.url.path == "/model/new"
        assert request.headers["Authorization"] == f"Bearer {_ADMIN}"
        if failure == "partial" and len(sent) == 1:
            return _ok()
        if failure in {"admin-status", "partial"}:
            return httpx.Response(401, json={"error": _SECRET})
        if failure == "typed-auth":
            try:
                raise RuntimeError(_SECRET)
            except RuntimeError as cause:
                raise LlmAuthError(_SECRET, status_code=401) from cause
        raise httpx.ReadTimeout(_SECRET, request=request)

    async def prepare() -> None:
        if failure == "callback":
            assert (await s.quota.balance("one-setup-probe")).held == 1
            raise RuntimeError(_SECRET)
        await s.prepare()

    with override_transport(httpx.MockTransport(respond)):
        with pytest.raises(ModelSetupError, match="registration failed") as caught:
            await s.complete(prepare)
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        row = await _assert_unknown_without_secret(s, caplog)
        before = len(sent)
        with pytest.raises(UnsafeEffectRetry):
            await s.complete(prepare)
        assert len(sent) == before and await s.rows() == [row]
    stats = s.stats()
    assert stats.available_keys == 1 and stats.blocked_keys == stats.cooling_down_keys == 0
    assert stats.total_error_count == stats.total_use_count == 0
    assert len(sent) == (0 if failure == "callback" else 2 if failure == "partial" else 1)


@pytest.mark.parametrize(
    "failure,status",
    [
        ("http", 401),
        ("http", 429),
        ("http", 503),
        ("typed", 401),
        ("typed", "malformed-secret-status"),
        ("typed", True),
        ("typed", 99),
        ("typed", 600),
        ("connect", None),
        ("timeout", None),
        ("generic", None),
    ],
)
async def test_post_setup_probe_errors_are_secret_free_unknown_and_not_retried(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str, status: Any
) -> None:
    s = await _setup(tmp_path)
    caplog.set_level("DEBUG")
    sent: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/model/new":
            return _ok()
        assert request.headers["Authorization"] == "Bearer fixture-key"
        if failure == "http":
            return httpx.Response(status, json={"error": _SECRET})
        if failure == "typed":
            try:
                raise RuntimeError(_SECRET)
            except RuntimeError as cause:
                error = LlmHttpError(_SECRET, status_code=status)
                raise error from cause
        if failure == "connect":
            raise httpx.ConnectError(_SECRET, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout(_SECRET, request=request)
        raise RuntimeError(_SECRET)

    with override_transport(httpx.MockTransport(respond)):
        with pytest.raises(RuntimeError, match="model gateway probe failed") as caught:
            await s.complete()
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert _SECRET not in str(caught.value)
        if failure == "typed":
            expected = status if type(status) is int and 100 <= status <= 599 else 0
            assert caught.value.status_code == expected
        row = await _assert_unknown_without_secret(s, caplog)
        with pytest.raises((UnsafeEffectRetry, CapabilityUnavailable)):
            await s.complete()
        assert len(sent) == 3 and await s.rows() == [row]
    stats = s.stats()
    assert stats.total_error_count == 1 and stats.total_use_count == 0
    assert stats.blocked_keys == int(status == 401)
    assert stats.cooling_down_keys == int(status == 429)


async def test_zero_quota_prevents_both_registration_and_probe(tmp_path: Path) -> None:
    s = await _setup(tmp_path, limit=0)
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _ok()

    with override_transport(httpx.MockTransport(respond)), pytest.raises(InvocationQuotaDenied):
        await s.complete()
    assert sent == []
    assert s.stats().total_error_count == s.stats().total_use_count == 0

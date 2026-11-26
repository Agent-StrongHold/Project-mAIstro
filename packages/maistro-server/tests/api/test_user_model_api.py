"""The HTTP user-model routes are a thin projection of UserModelService (#1047).

Every route derives the acting user from the authenticated principal, never
from the path or body; a foreign lineage is indistinguishable from a missing
one (404); and with no durable store configured the routes answer 503 rather
than serve facts that could not survive a restart.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.user_model import InMemoryUserModelStore, promote_evidence
from maistro.memory.user_model.service import UserModelService
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro_server.api import user_model as user_model_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal

STATEMENT = "owns a Canon 7D camera and 70-200mm lens"


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


async def _seed(store: InMemoryUserModelStore, user: str) -> str:
    fact = await promote_evidence(
        EpisodicMemory(
            tier=MemoryTier.OBSERVATION,
            content=STATEMENT,
            user_id=user,
            agent_id="agent-1",
            scope=MemoryScope.AGENT,
            project_id="proj-a",
            run_id="run-1",
        ),
        acting_user_id=user,
        store=store,
        audit_log=InMemoryAuditLog(),
        workspace_id="ws-a",
    )
    return fact.lineage_id


@pytest.fixture
async def api() -> AsyncIterator[tuple[FastAPI, TestClient, InMemoryUserModelStore, str]]:
    """One store seeded with the same fact for two colliding principals."""
    app = FastAPI()
    app.include_router(user_model_api.router)
    store = InMemoryUserModelStore()
    user_model_api.configure_user_model_service(
        UserModelService(store=store, audit_log=InMemoryAuditLog())
    )
    alice_lineage = await _seed(store, "alice")
    await _seed(store, "bob")
    app.dependency_overrides[verify_api_key] = lambda: _principal("alice")
    client = TestClient(app)
    try:
        yield app, client, store, alice_lineage
    finally:
        client.close()
        app.dependency_overrides.clear()
        user_model_api.configure_user_model_service(None)


def test_list_returns_only_the_authenticated_principals_facts(api) -> None:
    _app, client, _store, _lineage = api

    response = client.get("/user-model")
    assert response.status_code == 200
    facts = response.json()
    assert len(facts) == 1
    assert facts[0]["owner_user_id"] == "alice"
    assert facts[0]["statement"] == STATEMENT
    assert facts[0]["evidence"][0]["workspace_id"] == "ws-a"
    assert facts[0]["state"] == "active"


def test_correct_mark_private_and_forget_carry_provenance(api) -> None:
    _app, client, _store, lineage = api

    corrected = client.post(
        f"/user-model/{lineage}/correct",
        json={"statement": "owns a Sony A7 IV camera", "reason": "user correction"},
    )
    assert corrected.status_code == 200
    body = corrected.json()
    assert body["revision"] == 2
    assert body["correction"]["corrected_by"] == "alice"
    assert body["correction"]["reason"] == "user correction"

    privated = client.post(f"/user-model/{lineage}/mark-private", json={"reason": "too personal"})
    assert privated.status_code == 200
    assert privated.json()["reusable"] is False

    forgotten = client.delete(f"/user-model/{lineage}", params={"reason": "user asked"})
    assert forgotten.status_code == 200
    assert forgotten.json()["state"] == "tombstoned"
    # Deletion purges the statement; the response carries no fact content.
    assert forgotten.json()["statement"] == ""

    assert client.get("/user-model").json() == []


def test_foreign_lineage_is_a_404_not_an_authorization_disclosure(api) -> None:
    _app, client, _store, _lineage = api

    history = client.get("/user-model/some-lineage/history")
    assert history.status_code == 404
    forget = client.delete("/user-model/some-lineage", params={"reason": "nope"})
    assert forget.status_code == 404


def test_recall_is_relevance_gated_for_the_calling_principal(api) -> None:
    _app, client, _store, _lineage = api

    relevant = client.post(
        "/user-model/recall",
        json={"task_text": "which camera lens for the product shot", "workspace_id": "ws-b"},
    )
    assert relevant.status_code == 200
    items = relevant.json()
    assert [item["statement"] for item in items] == [STATEMENT]
    assert items[0]["score"] > 0.0

    unrelated = client.post(
        "/user-model/recall",
        json={"task_text": "refactor the payment parser module"},
    )
    assert unrelated.status_code == 200
    assert unrelated.json() == []


def test_unconfigured_service_is_a_503_never_a_fake_answer() -> None:
    app = FastAPI()
    app.include_router(user_model_api.router)
    app.dependency_overrides[verify_api_key] = lambda: _principal("alice")
    user_model_api.configure_user_model_service(None)
    client = TestClient(app)
    try:
        assert client.get("/user-model").status_code == 503
        recall = client.post("/user-model/recall", json={"task_text": "camera"})
        assert recall.status_code == 503
    finally:
        client.close()
        app.dependency_overrides.clear()


async def test_a_configured_runtime_binds_the_durable_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime with a spine pool and a session factory gets the durable twin.

    The complement of the 503 test above: once PostgreSQL is configured, the
    lifespan binds a ``UserModelService`` over ``PostgresUserModelStore`` —
    the Agent/API-shared service (#1047), not an in-process lookalike.
    Constructors are inert, so no server is needed to pin the wiring.
    """
    import maistro.memory.store as memory_store
    import maistro_server.main as main_module

    factory = object()
    monkeypatch.setattr(memory_store, "get_async_session_factory", lambda: factory)

    class _FakePool:
        pass

    try:
        await main_module._configure_user_model(_FakePool())

        service = user_model_api.get_user_model_service()
        assert isinstance(service, UserModelService)
        from maistro.memory.user_model.pg_store import PostgresUserModelStore

        assert isinstance(service.store, PostgresUserModelStore)
        assert service.store._factory is factory
    finally:
        user_model_api.configure_user_model_service(None)

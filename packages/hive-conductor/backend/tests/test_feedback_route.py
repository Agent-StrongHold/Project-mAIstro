"""Boy Scout — Phase 5 Signal #4 thumbs feedback route + service.

Two surfaces:

  POST /v1/dag-runs/{run_id}/feedback
  POST /v1/dag-runs/{run_id}/nodes/{node_id}/feedback

Asserts (no `isinstance`-only / no-op assertions; every check is on a
specific VALUE in the response, the recorded Outcome, or the audit log):

- Thumb up + thumb down are both recorded with the right fields
- The Outcome record carries the correct `thumb`, `thumb_comment`,
  `user_id`, `project_id`, `dag_run_id`, `node_id`, success=True
- Run-level feedback has empty node_id; per-node sets the node_id
- The audit_log entry has action="dag_feedback", actor=user_id,
  target=run_id, and detail.thumb matches the body
- Invalid thumb value → 400
- Unauthenticated request → 401
- get_experience_context surfaces the thumbs-down line scoped to the
  same project_id (Phase 2 isolation invariant preserved)
- Cross-project leak does NOT happen — a thumbs-down on Project A is
  not visible in Project B's prompt prelude
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture()
def fresh_outcome_store():
    """Bind a brand-new in-memory outcome store for each test so signals
    don't leak across tests."""
    import services.feedback_service as svc

    from maistro.memory.outcomes import InMemoryOutcomeStore

    previous = svc.get_outcome_store()
    store = InMemoryOutcomeStore()
    svc.set_outcome_store(store)
    yield store
    svc.set_outcome_store(previous)


# --- service unit tests ---------------------------------------------------


async def test_record_thumb_up_persists_outcome(fresh_outcome_store: Any) -> None:
    from services.feedback_service import record_thumb

    result = await record_thumb(
        user_id="u1",
        project_id="proj-A",
        run_id="run-001",
        thumb="up",
        comment="great",
        node_id="",
    )
    assert result["recorded"] is True
    assert result["outcome_id"] == 1
    assert result["signal"] == "user_thumb"
    assert len(fresh_outcome_store._outcomes) == 1
    o = fresh_outcome_store._outcomes[0]
    assert o.thumb == "up"
    assert o.thumb_comment == "great"
    assert o.user_id == "u1"
    assert o.project_id == "proj-A"
    assert o.dag_run_id == "run-001"
    assert o.node_id == ""
    assert o.success is True
    assert o.task_type == "dag_run"


async def test_record_thumb_down_with_node_id_sets_localization(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    await record_thumb(
        user_id="u2",
        project_id="proj-B",
        run_id="run-007",
        thumb="down",
        comment="filter was too aggressive",
        node_id="jira_epic_filter",
        dag_id="daily-status",
    )
    o = fresh_outcome_store._outcomes[0]
    assert o.thumb == "down"
    assert o.node_id == "jira_epic_filter"
    assert o.dag_id == "daily-status"
    assert o.thumb_comment == "filter was too aggressive"


async def test_record_thumb_invalid_value_raises_value_error(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    with pytest.raises(ValueError, match="thumb must be one of"):
        await record_thumb(
            user_id="u1",
            project_id="p",
            run_id="r",
            thumb="meh",
        )


async def test_record_thumb_empty_user_raises_value_error(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    with pytest.raises(ValueError, match="user_id is required"):
        await record_thumb(
            user_id="",
            project_id="p",
            run_id="r",
            thumb="up",
        )


async def test_record_thumb_empty_run_id_raises_value_error(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    with pytest.raises(ValueError, match="run_id is required"):
        await record_thumb(
            user_id="u",
            project_id="p",
            run_id="",
            thumb="up",
        )


def test_set_outcome_store_swaps_the_module_singleton() -> None:
    """The bridge / tests can hot-swap the store via set_outcome_store
    so the optimizer reads from the same instance the route writes to."""
    import services.feedback_service as svc

    from maistro.memory.outcomes import InMemoryOutcomeStore

    original = svc.get_outcome_store()
    new_store = InMemoryOutcomeStore()
    svc.set_outcome_store(new_store)
    try:
        assert svc.get_outcome_store() is new_store
        assert svc.get_outcome_store() is not original
    finally:
        svc.set_outcome_store(original)


# --- HTTP route tests ----------------------------------------------------


def _login_post(client: Any, run_id: str, body: dict[str, Any]) -> Any:
    return client.post(f"/v1/dag-runs/{run_id}/feedback", json=body)


def test_feedback_route_records_run_level_thumb_down(
    authed_client: Any, fresh_outcome_store: Any
) -> None:
    r = _login_post(
        authed_client,
        "run-A",
        {"thumb": "down", "comment": "stale data", "project_id": "proj-X"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is True
    assert body["signal"] == "user_thumb"
    assert body["outcome_id"] >= 1
    # Outcome content
    o = fresh_outcome_store._outcomes[-1]
    assert o.thumb == "down"
    assert o.thumb_comment == "stale data"
    assert o.dag_run_id == "run-A"
    assert o.node_id == ""  # run-level → empty
    assert o.project_id == "proj-X"


def test_feedback_route_records_per_node_thumb_up(
    authed_client: Any, fresh_outcome_store: Any
) -> None:
    r = authed_client.post(
        "/v1/dag-runs/run-B/nodes/jira_poll/feedback",
        json={"thumb": "up", "project_id": "proj-Y"},
    )
    assert r.status_code == 200, r.text
    o = fresh_outcome_store._outcomes[-1]
    assert o.dag_run_id == "run-B"
    assert o.node_id == "jira_poll"
    assert o.thumb == "up"
    assert o.project_id == "proj-Y"


def test_feedback_route_invalid_thumb_returns_422(
    authed_client: Any, fresh_outcome_store: Any
) -> None:
    """Pydantic Literal rejects values outside up|down with 422 (not 400)."""
    r = authed_client.post("/v1/dag-runs/run-C/feedback", json={"thumb": "maybe"})
    assert r.status_code == 422


def test_feedback_route_unauthenticated_returns_401() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)  # not logged in
    r = client.post("/v1/dag-runs/run-Z/feedback", json={"thumb": "up"})
    assert r.status_code == 401


def test_feedback_route_writes_audit_log(authed_client: Any, fresh_outcome_store: Any) -> None:
    import stores

    audit_count_before = len(stores.audit_log)
    r = authed_client.post(
        "/v1/dag-runs/run-Audit/feedback",
        json={"thumb": "down", "comment": "x" * 50, "project_id": "p"},
    )
    assert r.status_code == 200
    # New audit entry was created
    assert len(stores.audit_log) == audit_count_before + 1
    audit_entries = list(stores.audit_log.values())
    last = audit_entries[-1]
    assert last["action"] == "dag_feedback"
    assert last["target"] == "run-Audit"
    assert last["detail"]["thumb"] == "down"
    assert last["detail"]["project_id"] == "p"
    # Comment plaintext MUST NOT land in the audit log — only length
    assert "x" * 50 not in str(last["detail"])
    assert last["detail"]["comment_len"] == 50


def test_feedback_route_comment_too_long_returns_422(
    authed_client: Any, fresh_outcome_store: Any
) -> None:
    """Pydantic max_length=2000 rejects oversized comments."""
    r = authed_client.post(
        "/v1/dag-runs/run-Big/feedback",
        json={"thumb": "down", "comment": "x" * 2001},
    )
    assert r.status_code == 422


# --- outcome → next-run prompt invariant --------------------------------


async def test_thumbs_down_appears_in_same_project_experience_context(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    await record_thumb(
        user_id="u1",
        project_id="proj-Alpha",
        run_id="r1",
        thumb="down",
        comment="missed an epic",
        node_id="filter",
        task_type="pm_daily_status",
    )
    ctx = await fresh_outcome_store.get_experience_context(
        task_type="pm_daily_status",
        project_id="proj-Alpha",
    )
    assert "User Thumbs-Down Patterns" in ctx
    assert "missed an epic" in ctx
    assert "node=filter" in ctx


# --- helper-level branch coverage (defensive paths Pydantic normally pre-blocks) ---


def test_resolve_user_id_raises_401_when_user_missing() -> None:
    """If AuthMiddleware somehow let an unauthenticated request through
    (defensive coverage), _resolve_user_id raises 401 explicitly."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.feedback import _resolve_user_id

    request = SimpleNamespace(state=SimpleNamespace(user=None))
    with pytest.raises(HTTPException) as exc_info:
        _resolve_user_id(request)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 401


def test_resolve_user_id_raises_401_when_user_has_no_id() -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.feedback import _resolve_user_id

    request = SimpleNamespace(state=SimpleNamespace(user={"username": "x"}))
    with pytest.raises(HTTPException) as exc_info:
        _resolve_user_id(request)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 401


def test_resolve_project_id_falls_back_to_request_state_when_body_empty() -> None:
    from types import SimpleNamespace

    from routes.feedback import FeedbackBody, _resolve_project_id

    request = SimpleNamespace(state=SimpleNamespace(project_id="state-proj"))
    body = FeedbackBody(thumb="up")  # project_id defaults to ""
    assert _resolve_project_id(request, body) == "state-proj"  # type: ignore[arg-type]


def test_resolve_project_id_body_wins_over_state() -> None:
    from types import SimpleNamespace

    from routes.feedback import FeedbackBody, _resolve_project_id

    request = SimpleNamespace(state=SimpleNamespace(project_id="state-proj"))
    body = FeedbackBody(thumb="up", project_id="body-proj")
    assert _resolve_project_id(request, body) == "body-proj"  # type: ignore[arg-type]


def test_resolve_project_id_missing_state_returns_empty_string() -> None:
    """No body project_id + no request.state.project_id → empty fallback."""
    from types import SimpleNamespace

    from routes.feedback import FeedbackBody, _resolve_project_id

    request = SimpleNamespace(state=SimpleNamespace())  # no project_id attr
    body = FeedbackBody(thumb="up")
    assert _resolve_project_id(request, body) == ""  # type: ignore[arg-type]


async def test_record_feedback_rejects_invalid_thumb_at_runtime(
    fresh_outcome_store: Any,
) -> None:
    """Direct service-layer call — Pydantic's Literal can't intercept a
    handcrafted FeedbackBody constructed with thumb='bad'. Confirms the
    in-function defense fires."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.feedback import FeedbackBody, _record_feedback

    # Bypass Pydantic by mutating the field after construction.
    body = FeedbackBody(thumb="up")
    object.__setattr__(body, "thumb", "bad")  # type: ignore[attr-defined]
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "u1"}))
    with pytest.raises(HTTPException) as exc_info:
        await _record_feedback(request, run_id="r", node_id="", body=body)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 400
    assert "thumb must be one of" in exc_info.value.detail


async def test_record_feedback_per_node_route_requires_non_empty_node_id(
    fresh_outcome_store: Any,
) -> None:
    """Direct call into the node route handler with empty node_id —
    FastAPI's path parser blocks this in HTTP, but the in-function
    defensive check must still exist + work for service-layer callers."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.feedback import FeedbackBody, submit_node_feedback

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "u1"}))
    body = FeedbackBody(thumb="up")
    with pytest.raises(HTTPException) as exc_info:
        await submit_node_feedback(
            run_id="r",
            node_id="",
            body=body,
            request=request,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 400
    assert "node_id is required" in exc_info.value.detail


async def test_record_feedback_translates_value_error_to_400(
    authed_client: Any,
    fresh_outcome_store: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If record_thumb raises ValueError (e.g. service-level invariant
    fails) the route maps it to 400 instead of 500."""
    import services.feedback_service as svc

    async def _raise(**kwargs: Any) -> Any:
        raise ValueError("invariant broken")

    monkeypatch.setattr(svc, "record_thumb", _raise)
    # Also patch the route module's reference (it imported by name)
    import routes.feedback as fb

    monkeypatch.setattr(fb, "record_thumb", _raise)

    r = authed_client.post("/v1/dag-runs/run-V/feedback", json={"thumb": "up"})
    assert r.status_code == 400
    assert "invariant broken" in r.json()["detail"]


async def test_cross_project_thumb_does_not_leak(
    fresh_outcome_store: Any,
) -> None:
    from services.feedback_service import record_thumb

    await record_thumb(
        user_id="u1",
        project_id="proj-Alpha",
        run_id="r1",
        thumb="down",
        comment="alpha-only signal",
        task_type="pm_daily_status",
    )
    ctx_other = await fresh_outcome_store.get_experience_context(
        task_type="pm_daily_status",
        project_id="proj-Beta",
    )
    assert "alpha-only signal" not in ctx_other
    assert ctx_other == ""  # no signals for Beta project at all

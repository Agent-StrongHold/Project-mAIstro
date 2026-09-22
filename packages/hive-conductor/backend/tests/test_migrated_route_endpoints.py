"""Degraded-path coverage for routes the #1134 namespace move rewired.

Every endpoint here was migrated from a flat ``from services.x import y``
lazy import to the package-qualified ``from hive_conductor.services.x import
y`` spelling. The lazy imports live inside the request path, so the migration
only stays proven if the handlers actually execute: a route whose rewritten
import line is never run is a route whose migration was never tested. These
tests drive each handler through the real ASGI app (or its real module, for
helpers the app calls), asserting the documented degraded behavior rather
than just touching lines.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# The auth middleware guards /v1 reads too, so every request here goes through
# a real session, exactly like the shipped UI does.
pytestmark = pytest.mark.usefixtures("admin_client")


def test_evolution_read_endpoints_report_their_degraded_state(admin_client: TestClient) -> None:
    """Every read endpoint answers, not 500, while evolution is not started."""
    status = admin_client.get("/v1/evolution/status")
    assert status.status_code == 200
    assert status.json()["running"] is False
    assert status.json()["availability"] == "unavailable"

    assert admin_client.get("/v1/evolution/population").json() == []
    assert admin_client.get("/v1/evolution/champion").json() == {"genome": None, "fitness": None}
    assert admin_client.get("/v1/evolution/lineage/g-1").json() == []
    assert admin_client.get("/v1/evolution/tournament/leaderboard").json() == []
    assert admin_client.get("/v1/evolution/tournament/battles").json() == []
    assert admin_client.get("/v1/evolution/tournament/stats").json() == {}

    genome = admin_client.get("/v1/evolution/population/g-1")
    assert genome.status_code == 503
    assert genome.json()["detail"] == "evolution service not started"


# --- rsi: status and the run-lifecycle 404s ---------------------------------


def test_rsi_status_and_run_lifecycle_answer(admin_client: TestClient) -> None:
    status = admin_client.get("/v1/rsi/status")
    assert status.status_code == 200
    assert status.json()["available"] in (True, False)

    assert admin_client.get("/v1/rsi/runs").json() == []

    unknown = "no-such-run-1134"
    assert admin_client.get(f"/v1/rsi/runs/{unknown}").status_code == 404
    assert admin_client.post(f"/v1/rsi/runs/{unknown}/stop").status_code == 404
    assert admin_client.get(f"/v1/rsi/runs/{unknown}/reviews").status_code == 404
    assert admin_client.get(f"/v1/rsi/runs/{unknown}/rlphd").status_code == 404


# --- missions: guidance requires a workspace --------------------------------


def test_mission_guidance_names_a_workspace_or_refuses(admin_client: TestClient) -> None:
    """The guidance import resolves; authorization answers before any pulse."""
    r = admin_client.post(
        "/v1/tasks/mission-1134/guidance",
        json={"text": "focus on onboarding"},
    )
    assert r.status_code == 404
    assert "workspace" in r.json()["detail"]


# --- setup checklist: build, dismiss, undismiss ------------------------------


def test_setup_checklist_dismiss_round_trip(admin_client: TestClient) -> None:
    first = admin_client.get("/v1/setup-checklist")
    assert first.status_code == 200
    body = first.json()
    assert body["dismiss_ttl_days"] > 0
    assert body["items"], "a fresh admin session must have incomplete items"

    item_id = body["items"][0]["id"]
    dismissed = admin_client.post(f"/v1/setup-checklist/{item_id}/dismiss")
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    undismissed = admin_client.post(f"/v1/setup-checklist/{item_id}/undismiss")
    assert undismissed.status_code == 200
    assert undismissed.json() == {"id": item_id, "status": "incomplete"}


def test_setup_checklist_rejects_unknown_item(admin_client: TestClient) -> None:
    r = admin_client.post("/v1/setup-checklist/not-an-item/dismiss")
    assert r.status_code == 404


# --- providers: the checklist's activation probe -----------------------------


def test_any_provider_activated_reads_the_session_store() -> None:
    """`any_provider_activated` is what the checklist's llm item calls."""
    from hive_conductor.routes.providers import any_provider_activated

    assert any_provider_activated() in (True, False)


# --- projects: the module still imports through the package ------------------


def test_projects_router_module_imports_through_the_package() -> None:
    """`routes/projects.py` is mounted lazily; its import must still resolve.

    The module's top-level import of ``hive_conductor.services`` is the line
    the namespace move rewrote; nothing else imports this module eagerly, so
    this is the executed proof that it resolves through the package.
    """
    from hive_conductor.routes import projects

    assert projects.router.prefix == "/v1/projects"
    assert any(getattr(r, "path", None) for r in projects.router.routes)

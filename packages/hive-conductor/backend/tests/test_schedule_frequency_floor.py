"""The `/v1/schedules` frequency floor and catch-up window bound (#1200).

The substrate measures (`maistro.scheduling.cron.minimum_gap`) and caps the
window at seven days; the product decides the floor and its own, tighter
window cap via operator settings that are themselves bounded at startup.
These tests pin the product half of that contract: what a client may file,
what is refused as a 422, and that the effective recurrence — not the field
that happened to be edited — is what the floor applies to.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_TPL = "floor-template"


async def _bind_workspace() -> str:
    from services import workspace_authority

    workspace = await workspace_authority.create_workspace(
        creator_user_id="user-1",
        name="Frequency floor",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    await workspace_authority.set_member(workspace.id, user_id="admin", role="editor")
    return str(workspace.id)


@pytest.fixture
def configured() -> Iterator[Any]:
    """A real Container behind the engine, the same seam the routes write."""
    import services.engine as engine_mod

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = asyncio.run(create_container(AgentConfig(router_api_key="test-key")))
    service = engine_mod.get_engine()
    previous = service._agent_port
    service._agent_port = SimpleNamespace(container=container)
    try:
        container.test_workspace = asyncio.run(_bind_workspace())
        yield container
    finally:
        service._agent_port = previous
        asyncio.run(container.aclose())


def _create(client: Any, workspace_id: str, **overrides: Any) -> Any:
    body = {
        "name": "quarterly",
        "cron_expression": "*/15 * * * *",
        "mission_template_id": _TPL,
        "workspace_id": workspace_id,
        **overrides,
    }
    return client.post("/v1/schedules", json=body)


def _raise_floor(monkeypatch: pytest.MonkeyPatch, seconds: str) -> None:
    from config import get_settings

    monkeypatch.setenv("SCHEDULE_MIN_FREQUENCY_GAP_S", seconds)
    get_settings.cache_clear()


def _restore_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings

    monkeypatch.undo()
    get_settings.cache_clear()


# --- the frequency floor -----------------------------------------------------


def test_a_per_minute_schedule_is_refused_at_create(admin_client: Any, configured: Any) -> None:
    response = _create(admin_client, configured.test_workspace, cron_expression="* * * * *")
    assert response.status_code == 422, response.text
    assert "schedule_min_frequency_gap_s" in response.text
    # Nothing was filed under the refused recurrence.
    assert asyncio.run(configured.schedule_store.get(response.json().get("id", ""))) is None


def test_a_measured_list_form_gap_is_refused(admin_client: Any, configured: Any) -> None:
    """`0,5,10 * * * *` is a five-minute schedule, not an hourly one — the
    floor measures real consecutive fire times (ADR-082126-f69c §7)."""
    response = _create(admin_client, configured.test_workspace, cron_expression="0,5,10 * * * *")
    assert response.status_code == 422, response.text


def test_the_reference_fifteen_minute_floor_is_accepted(admin_client: Any, configured: Any) -> None:
    response = _create(admin_client, configured.test_workspace)
    assert response.status_code == 201, response.text
    sid = response.json()["id"]
    canonical = asyncio.run(configured.schedule_store.get(sid))
    assert canonical is not None
    assert canonical.cron == "*/15 * * * *"


def test_an_update_below_the_floor_is_refused_but_a_rename_is_not(
    admin_client: Any, configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor applies to the *effective* recurrence: an edit that touches
    cron or zone must satisfy it, while a rename of a schedule filed before
    the floor was raised stays legal — refusing it would strand the row."""
    created = _create(admin_client, configured.test_workspace)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    _raise_floor(monkeypatch, "3600")
    try:
        renamed = admin_client.put(f"/v1/schedules/{sid}", json={"name": "renamed"})
        assert renamed.status_code == 200, renamed.text

        recurred = admin_client.put(
            f"/v1/schedules/{sid}", json={"cron_expression": "*/15 * * * *"}
        )
        assert recurred.status_code == 422, recurred.text
        assert "schedule_min_frequency_gap_s" in recurred.text
    finally:
        _restore_settings(monkeypatch)


# --- the product catch-up window cap ----------------------------------------


def test_a_window_over_the_operator_cap_is_refused(admin_client: Any) -> None:
    response = _create(admin_client, "", catchup_window_seconds=86_401.0)
    assert response.status_code == 422, response.text
    assert "schedule_max_catchup_window_s" in response.text


def test_a_window_over_the_substrate_ceiling_is_refused(admin_client: Any) -> None:
    response = _create(admin_client, "", catchup_window_seconds=604_801.0)
    assert response.status_code == 422, response.text


def test_a_negative_window_is_refused(admin_client: Any) -> None:
    response = _create(admin_client, "", catchup_window_seconds=-1.0)
    assert response.status_code == 422, response.text


def test_a_window_within_the_cap_reaches_the_canonical_row(
    admin_client: Any, configured: Any
) -> None:
    response = _create(admin_client, configured.test_workspace, catchup_window_seconds=7_200.0)
    assert response.status_code == 201, response.text
    sid = response.json()["id"]
    canonical = asyncio.run(configured.schedule_store.get(sid))
    assert canonical is not None
    assert canonical.catchup_window_seconds == 7_200.0


def test_a_window_update_is_projected_to_the_canonical_row(
    admin_client: Any, configured: Any
) -> None:
    created = _create(admin_client, configured.test_workspace)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    updated = admin_client.put(f"/v1/schedules/{sid}", json={"catchup_window_seconds": 10_800.0})
    assert updated.status_code == 200, updated.text
    canonical = asyncio.run(configured.schedule_store.get(sid))
    assert canonical is not None
    assert canonical.catchup_window_seconds == 10_800.0


# --- the operator bounds on the floor/cap settings themselves ---------------


def test_floor_and_cap_settings_outside_the_safe_bounds_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misconfigured floor must fail loudly, not clamp: an operator who
    asked for a 60s floor must not quietly get 300s and start admitting
    schedules they believed forbidden (#1200)."""
    from config import get_settings

    for env, value in (
        ("SCHEDULE_MIN_FREQUENCY_GAP_S", "299"),
        ("SCHEDULE_MIN_FREQUENCY_GAP_S", "604801"),
        ("SCHEDULE_MAX_CATCHUP_WINDOW_S", "3599"),
        ("SCHEDULE_MAX_CATCHUP_WINDOW_S", "604801"),
    ):
        monkeypatch.setenv(env, value)
        get_settings.cache_clear()
        try:
            with pytest.raises(Exception, match="must be between"):
                get_settings()
        finally:
            monkeypatch.delenv(env)
            get_settings.cache_clear()


def test_boundary_settings_at_the_safe_bounds_are_accepted() -> None:
    from config import Settings

    settings = Settings(
        schedule_min_frequency_gap_s=300,
        schedule_max_catchup_window_s=604_800,
    )
    assert settings.schedule_min_frequency_gap_s == 300
    assert settings.schedule_max_catchup_window_s == 604_800

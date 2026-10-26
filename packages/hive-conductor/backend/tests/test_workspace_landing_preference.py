"""Workspace product preferences on the canonical profile (#1050).

Landing path + restore aggressiveness live on the same profile document so UI,
PUT/PATCH /v1/profile, and chat ``profile_set`` share one durable owner.
Missing or unknown values mean Workspace Home / balanced restore — never a
second browser-local product authority.
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Iterator

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from routes.audit import log_audit  # noqa: E402
from services import chat_completion, profile_store  # noqa: E402
from services.workspace_preferences import (  # noqa: E402
    LANDING_KEY,
    RESTORE_ABSOLUTE_MS,
    RESTORE_KEY,
    SUGGESTION_COOLDOWN_KEY,
    PreferenceValueError,
    interpret_restore_aggressiveness_request,
    normalize_landing_path,
    normalize_restore_aggressiveness,
    restore_window_ms,
    validate_preference_field,
)

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(autouse=True)
def _fresh_store() -> Iterator[None]:
    """Every test starts on its own ephemeral store and leaves nothing behind."""
    profile_store.reset()
    yield
    profile_store.reset()


def test_profile_schema_lists_workspace_preference_keys() -> None:
    prefs = chat_completion.PROFILE_SCHEMA["preferences"]
    assert LANDING_KEY in prefs
    assert RESTORE_KEY in prefs


def test_landing_preference_round_trips_on_the_profile_store() -> None:
    profile_store.set_field("admin", LANDING_KEY, "/chat")
    assert profile_store.preferences("admin")[LANDING_KEY] == "/chat"

    # Same field chat profile_set writes — a second write replaces, not forks.
    profile_store.set_field("admin", LANDING_KEY, "/goals")
    assert profile_store.preferences("admin")[LANDING_KEY] == "/goals"


def test_landing_preference_is_per_user() -> None:
    profile_store.set_field("admin", LANDING_KEY, "/chat")
    profile_store.set_field("pmuser", LANDING_KEY, "/backlog")
    assert profile_store.preferences("admin")[LANDING_KEY] == "/chat"
    assert profile_store.preferences("pmuser")[LANDING_KEY] == "/backlog"


def test_restore_aggressiveness_round_trips() -> None:
    profile_store.set_field("admin", RESTORE_KEY, "generous")
    assert profile_store.preferences("admin")[RESTORE_KEY] == "generous"
    profile_store.set_field("admin", RESTORE_KEY, "off")
    assert profile_store.preferences("admin")[RESTORE_KEY] == "off"


def test_invalid_landing_path_is_refused_on_write() -> None:
    with pytest.raises(PreferenceValueError, match="workspace_default_landing"):
        profile_store.set_field("admin", LANDING_KEY, "/dashboard")
    assert LANDING_KEY not in profile_store.preferences("admin")


def test_invalid_restore_band_is_refused_on_write() -> None:
    with pytest.raises(PreferenceValueError, match="workspace_restore_aggressiveness"):
        profile_store.set_field("admin", RESTORE_KEY, "always")
    assert RESTORE_KEY not in profile_store.preferences("admin")


def test_normalize_helpers_fall_back_safely() -> None:
    assert normalize_landing_path("/evil") == "/home"
    assert normalize_landing_path("../x") == "/home"
    assert normalize_landing_path("/chat?x=1") == "/chat"
    assert normalize_restore_aggressiveness("ALWAYS") == "balanced"
    assert normalize_restore_aggressiveness("Generous") == "generous"


def test_validate_preference_field_passes_unknown_keys() -> None:
    assert validate_preference_field("name", "Blake") == "Blake"


def test_patch_refuses_invalid_landing_with_http_400(authed_client) -> None:
    """PreferenceValueError on PATCH must surface as 400 (routes/profile.py)."""
    response = authed_client.patch(
        "/v1/profile",
        json={"field": LANDING_KEY, "value": "/dashboard"},
    )
    assert response.status_code == 400
    assert LANDING_KEY in response.json()["detail"]
    # Nothing durable was written for any principal — refused before commit.
    assert all(
        LANDING_KEY not in profile_store.preferences(uid) for uid in profile_store.user_ids()
    )


def test_put_refuses_invalid_restore_with_http_400(authed_client) -> None:
    """PreferenceValueError on PUT must surface as 400 (routes/profile.py)."""
    response = authed_client.put(
        "/v1/profile",
        json={"preferences": {RESTORE_KEY: "always"}},
    )
    assert response.status_code == 400
    assert RESTORE_KEY in response.json()["detail"]


async def test_profile_set_tool_refuses_invalid_landing() -> None:
    """Chat profile_set maps PreferenceValueError to a model-readable error."""
    result = await chat_completion._tool_profile_set(
        {"field": LANDING_KEY, "value": "/dashboard"},
        "admin",
    )
    assert "error" in result
    assert LANDING_KEY in result["error"]
    assert result.get("updated") is not True
    assert LANDING_KEY not in profile_store.preferences("admin")


def test_hold_onto_sessions_longer_maps_to_generous() -> None:
    """Natural-language restore request pins the generous band (#1050)."""
    assert (
        interpret_restore_aggressiveness_request(
            "hold onto my sessions longer and take me back when I come back"
        )
        == "generous"
    )
    assert interpret_restore_aggressiveness_request("never restore this tab") == "off"
    assert interpret_restore_aggressiveness_request("unrelated") is None


def test_generous_band_expands_restore_window_vs_balanced() -> None:
    """Changing aggressiveness to generous materially expands the window."""
    left_at = 1_700_000_000_000
    session_started = left_at - 60_000
    balanced = restore_window_ms(
        "balanced", left_at_ms=left_at, session_started_at_ms=session_started
    )
    generous = restore_window_ms(
        "generous", left_at_ms=left_at, session_started_at_ms=session_started
    )
    assert generous > balanced
    assert generous == RESTORE_ABSOLUTE_MS["generous"]
    away_ms = balanced + 60_000
    assert away_ms > balanced
    assert away_ms <= generous


async def test_agent_profile_set_hold_sessions_longer_writes_same_restore_key() -> None:
    """Agent tool path sets RESTORE_KEY=generous via the same durable owner."""
    stores.audit_log.clear()
    direct = await chat_completion._tool_profile_set(
        {"field": RESTORE_KEY, "value": "generous"},
        "admin",
    )
    assert direct == {"updated": True, "field": RESTORE_KEY, "value": "generous"}
    assert profile_store.preferences("admin")[RESTORE_KEY] == "generous"

    phrase = await chat_completion._tool_profile_set(
        {
            "field": RESTORE_KEY,
            "value": "hold onto my sessions longer and take me back when I come back",
        },
        "admin",
    )
    assert phrase["updated"] is True
    assert phrase["value"] == "generous"
    assert profile_store.preferences("admin")[RESTORE_KEY] == "generous"

    left_at = 1_700_000_000_000
    window = restore_window_ms(
        profile_store.preferences("admin")[RESTORE_KEY],
        left_at_ms=left_at,
        session_started_at_ms=left_at - 60_000,
    )
    assert window == RESTORE_ABSOLUTE_MS["generous"]


async def test_agent_workspace_preference_set_is_audited_and_reversible() -> None:
    """Agent preference mutations leave an audit trail; PATCH can reverse them."""
    stores.audit_log.clear()
    result = await chat_completion._tool_profile_set(
        {"field": LANDING_KEY, "value": "/goals"},
        "admin",
    )
    assert result["updated"] is True

    audited = [
        e
        for e in stores.audit_log.values()
        if e.get("action") == "profile_preference_set" and e.get("target") == LANDING_KEY
    ]
    assert len(audited) == 1
    assert audited[0]["actor"] == "admin"
    assert audited[0]["detail"]["source"] == "agent"
    assert audited[0]["detail"]["value"] == "/goals"

    profile_store.set_field("admin", LANDING_KEY, "/home")
    assert profile_store.preferences("admin")[LANDING_KEY] == "/home"


def test_patch_workspace_preference_is_audited(authed_client) -> None:
    """UI/API PATCH of a Workspace preference key is auditable (#1050)."""
    stores.audit_log.clear()
    response = authed_client.patch(
        "/v1/profile",
        json={"field": RESTORE_KEY, "value": "brief"},
    )
    assert response.status_code == 200
    audited = [
        e
        for e in stores.audit_log.values()
        if e.get("action") == "profile_preference_set" and e.get("target") == RESTORE_KEY
    ]
    assert len(audited) == 1
    assert audited[0]["detail"]["source"] == "api"
    assert audited[0]["detail"]["value"] == "brief"


def test_suggestion_cooldown_round_trips_on_profile() -> None:
    """Dismiss cooldown is a durable profile preference, not browser-only."""
    until = 1_800_000_000_000
    profile_store.set_field("admin", SUGGESTION_COOLDOWN_KEY, {"/goals": until})
    assert profile_store.preferences("admin")[SUGGESTION_COOLDOWN_KEY] == {"/goals": until}


def test_invalid_suggestion_cooldown_is_refused() -> None:
    with pytest.raises(PreferenceValueError, match="workspace_landing_suggestion_cooldown"):
        profile_store.set_field("admin", SUGGESTION_COOLDOWN_KEY, {"/home": 1})
    with pytest.raises(PreferenceValueError, match="workspace_landing_suggestion_cooldown"):
        profile_store.set_field("admin", SUGGESTION_COOLDOWN_KEY, "nope")


def test_profile_schema_lists_suggestion_cooldown() -> None:
    prefs = chat_completion.PROFILE_SCHEMA["preferences"]
    assert SUGGESTION_COOLDOWN_KEY in prefs


def test_ordinary_profile_fields_are_not_audited_as_workspace_prefs() -> None:
    """Name/role writes stay off the settings preference trail."""
    stores.audit_log.clear()
    from services.workspace_preferences import audit_workspace_preference

    audit_workspace_preference(actor="admin", field="name", value="Blake", source="agent")
    assert not any(
        e.get("action") == "profile_preference_set" for e in stores.audit_log.values()
    )
    log_audit("login", "someone")
    audit_workspace_preference(
        actor="admin", field=RESTORE_KEY, value="off", source="agent"
    )
    assert (
        sum(1 for e in stores.audit_log.values() if e.get("action") == "profile_preference_set")
        == 1
    )

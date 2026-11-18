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
    LEARNED_STREAK_MIN,
    RESTORE_ABSOLUTE_MS,
    RESTORE_KEY,
    SUGGESTION_COOLDOWN_KEY,
    PreferenceValueError,
    decide_landing,
    decide_landing_suggestion,
    interpret_restore_aggressiveness_request,
    normalize_landing_path,
    normalize_restore_aggressiveness,
    normalize_restore_path,
    normalize_suggestion_cooldown,
    record_immediate_landing_hop,
    restore_window_ms,
    suggestion_on_cooldown,
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


def test_settings_audit_view_serves_preference_changes(admin_client) -> None:
    """The settings audit trail surfaces Workspace preference writes (#1050).

    `GET /v1/settings/audit` serves `profile_preference_set` rows from the one
    durable audit log, so a user can see Agent/API preference changes where
    settings changes are shown — without a second log.
    """
    stores.audit_log.clear()
    response = admin_client.patch(
        "/v1/profile",
        json={"field": LANDING_KEY, "value": "/goals"},
    )
    assert response.status_code == 200
    trail = admin_client.get("/v1/settings/audit")
    assert trail.status_code == 200
    preference_rows = [e for e in trail.json() if e["action"] == "profile_preference_set"]
    assert preference_rows, "settings audit view must surface preference writes"
    row = preference_rows[0]
    assert row["target"] == LANDING_KEY
    assert row["detail"]["source"] == "api"
    assert row["detail"]["value"] == "/goals"


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
    assert not any(e.get("action") == "profile_preference_set" for e in stores.audit_log.values())
    log_audit("login", "someone")
    audit_workspace_preference(actor="admin", field=RESTORE_KEY, value="off", source="agent")
    assert (
        sum(1 for e in stores.audit_log.values() if e.get("action") == "profile_preference_set")
        == 1
    )


# --- degenerate paths of the policy helpers (diff-coverage 90% floor) ---


def test_interpret_restore_request_rejects_non_string_and_blank() -> None:
    """Non-string and whitespace-only requests name no band."""
    assert interpret_restore_aggressiveness_request(None) is None  # type: ignore[arg-type]
    assert interpret_restore_aggressiveness_request(7) is None  # type: ignore[arg-type]
    assert interpret_restore_aggressiveness_request("   \n\t") is None


def test_interpret_restore_request_brief_restore_maps_to_brief() -> None:
    """A short-window restore request maps to the brief band, nothing else."""
    assert interpret_restore_aggressiveness_request("restore me for a brief moment") == "brief"
    assert interpret_restore_aggressiveness_request("BRIEF restore please") == "brief"
    # "brief" alone (no restore) is not a restore policy phrase.
    assert interpret_restore_aggressiveness_request("keep it brief") is None


def test_normalize_restore_path_rejects_non_surfaces() -> None:
    """Only recorded restore-eligible surfaces may be reopened."""
    assert normalize_restore_path(None) is None  # type: ignore[arg-type]
    assert normalize_restore_path(123) is None  # type: ignore[arg-type]
    assert normalize_restore_path("chat") is None  # not root-relative
    assert normalize_restore_path("//evil.example") is None  # scheme-relative
    assert normalize_restore_path("/dashboard") is None  # valid shape, not a restore surface
    assert normalize_restore_path("/attention?tab=x#row") == "/attention"


def test_decide_landing_names_a_reason_for_every_recent_row_shape() -> None:
    """No recent row, a bad path, bad timestamps or a future left_at never restores."""
    now = 1_700_000_000_000
    default_landing = "/home"
    # No observation at all: plain default, not "off" and not a restore.
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent={},
        now_ms=now,
    ) == {"path": "/home", "reason": "default"}
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent=None,
        now_ms=now,
    ) == {"path": "/home", "reason": "default"}
    # A path that is not a restore surface is invalid, never a restore.
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent={"path": "/dashboard", "left_at_ms": now - 1000},
        now_ms=now,
    ) == {"path": "/home", "reason": "invalid"}
    # Non-integer timestamps are invalid.
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent={"path": "/chat", "left_at_ms": "soon"},
        now_ms=now,
    ) == {"path": "/home", "reason": "invalid"}
    # A left_at in the future cannot restore — the row is corrupt.
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent={"path": "/chat", "left_at_ms": now + 5000},
        now_ms=now,
    ) == {"path": "/home", "reason": "invalid"}
    # Control: inside the window the surface is restored.
    assert decide_landing(
        aggressiveness="balanced",
        default_landing=default_landing,
        recent={"path": "/chat", "left_at_ms": now - 1000},
        now_ms=now,
    ) == {"path": "/chat", "reason": "restore"}


def test_record_immediate_landing_hop_ignores_non_surfaces_and_bad_streaks() -> None:
    """Home hops and non-surfaces preserve the prior pattern; junk streaks restart."""
    now = 1_700_000_000_000
    prior = {"path": "/goals", "streak": 2, "last_at_ms": now - 1000}
    # A hop back to Home is not a surface preference.
    assert record_immediate_landing_hop(prior, "/home", now) is prior
    # A non-landing surface is not one either.
    assert record_immediate_landing_hop(prior, "/dashboard", now) is prior
    # A prior streak that is not an int restarts at 1 rather than crashing.
    restarted = record_immediate_landing_hop({"path": "/chat", "streak": "junk"}, "/chat", now)
    assert restarted == {"path": "/chat", "streak": 1, "last_at_ms": now}
    # Control: the same surface increments the streak.
    grown = record_immediate_landing_hop(
        {"path": "/chat", "streak": 2, "last_at_ms": now - 1000}, "/chat", now
    )
    assert grown == {"path": "/chat", "streak": 3, "last_at_ms": now}


def test_decide_landing_suggestion_refuses_insufficient_and_ineligible_patterns() -> None:
    """No pattern, a Home/non-surface path, or an unreadable streak proposes nothing."""
    assert decide_landing_suggestion(
        pattern=None, explicit_default="/home", suppressed_paths=frozenset()
    ) == (False, "insufficient")
    assert decide_landing_suggestion(
        pattern={}, explicit_default="/home", suppressed_paths=frozenset()
    ) == (False, "insufficient")
    # The current default itself is never proposed as the learned default.
    assert decide_landing_suggestion(
        pattern={"path": "/home", "streak": LEARNED_STREAK_MIN},
        explicit_default="/home",
        suppressed_paths=frozenset(),
    ) == (False, "ineligible")
    # A path outside the allow-list is ineligible too.
    assert decide_landing_suggestion(
        pattern={"path": "/dashboard", "streak": LEARNED_STREAK_MIN},
        explicit_default="/home",
        suppressed_paths=frozenset(),
    ) == (False, "ineligible")
    # A streak that is not an int is insufficient evidence.
    assert decide_landing_suggestion(
        pattern={"path": "/chat", "streak": "junk"},
        explicit_default="/home",
        suppressed_paths=frozenset(),
    ) == (False, "insufficient")
    assert decide_landing_suggestion(
        pattern={"path": "/chat"},
        explicit_default="/home",
        suppressed_paths=frozenset(),
    ) == (False, "insufficient")
    # Control: an eligible pattern with enough streak proposes itself.
    assert decide_landing_suggestion(
        pattern={"path": "/chat", "streak": LEARNED_STREAK_MIN},
        explicit_default="/home",
        suppressed_paths=frozenset(),
    ) == (True, "/chat")


def test_normalize_suggestion_cooldown_drops_unusable_entries() -> None:
    """Non-surfaces, the default, non-integer and non-positive untils are dropped."""
    until = 1_800_000_000_000
    assert normalize_suggestion_cooldown("nope") == {}
    assert normalize_suggestion_cooldown(None) == {}
    assert normalize_suggestion_cooldown(
        {
            "/goals": until,  # kept
            "/chat": str(until),  # numeric strings coerce
            "/home": until,  # the default itself is never a suggestion
            "/dashboard": until,  # not an allow-listed surface
            "/backlog": "soon",  # not an integer
            "/work-items": 0,  # not positive
            "/dags": -5,  # not positive
        }
    ) == {"/goals": until, "/chat": until}


def test_suggestion_on_cooldown_needs_a_stored_entry_for_the_path() -> None:
    """A cooldown map without the path never suppresses it."""
    now = 1_700_000_000_000
    until = now + 60_000
    cooldown = {"/goals": until}
    assert suggestion_on_cooldown(cooldown, "/chat", now_ms=now) is False
    assert suggestion_on_cooldown(cooldown, "/home", now_ms=now) is False
    assert suggestion_on_cooldown(None, "/chat", now_ms=now) is False
    # Stored and unexpired: suppressed. Stored but expired: not.
    assert suggestion_on_cooldown(cooldown, "/goals", now_ms=now) is True
    assert suggestion_on_cooldown(cooldown, "/goals", now_ms=until) is False


def test_validate_refuses_non_string_landing_and_restore_values() -> None:
    """Non-string values are refused, not coerced (400 on PUT/PATCH)."""
    with pytest.raises(PreferenceValueError, match="must be a path string"):
        validate_preference_field(LANDING_KEY, 123)  # type: ignore[arg-type]
    with pytest.raises(PreferenceValueError, match="must be a string"):
        validate_preference_field(RESTORE_KEY, ["generous"])  # type: ignore[arg-type]


def test_validate_cooldown_refuses_non_path_keys_and_bad_values() -> None:
    """Cooldown maps validate keys and until-values before any write lands."""
    with pytest.raises(PreferenceValueError, match="keys must be paths"):
        validate_preference_field(SUGGESTION_COOLDOWN_KEY, {7: 1_800_000_000_000})
    with pytest.raises(PreferenceValueError, match="values must be epoch-ms integers"):
        validate_preference_field(SUGGESTION_COOLDOWN_KEY, {"/goals": "soon"})
    with pytest.raises(PreferenceValueError, match="values must be positive epoch-ms"):
        validate_preference_field(SUGGESTION_COOLDOWN_KEY, {"/goals": 0})
    with pytest.raises(PreferenceValueError, match="values must be positive epoch-ms"):
        validate_preference_field(SUGGESTION_COOLDOWN_KEY, {"/goals": -1})


def test_put_workspace_preferences_are_audited_including_the_cooldown_map(
    authed_client,
) -> None:
    """PUT (full replace) audits Workspace keys; cooldown maps summarize paths.

    The audit entry for the cooldown map carries the sorted surface list rather
    than every until-ms, so the trail stays readable at any map size.
    """
    stores.audit_log.clear()
    until = 1_800_000_000_000
    response = authed_client.put(
        "/v1/profile",
        json={
            "preferences": {
                "name": "Blake",  # ordinary field: not a preference audit
                RESTORE_KEY: "generous",
                SUGGESTION_COOLDOWN_KEY: {
                    "/chat": until,
                    "/goals": until,
                },
            }
        },
    )
    assert response.status_code == 200
    rows = [e for e in stores.audit_log.values() if e.get("action") == "profile_preference_set"]
    by_field = {e["target"]: e for e in rows}
    assert set(by_field) == {RESTORE_KEY, SUGGESTION_COOLDOWN_KEY}
    assert by_field[RESTORE_KEY]["detail"] == {
        "field": RESTORE_KEY,
        "source": "api",
        "value": "generous",
    }
    assert by_field[SUGGESTION_COOLDOWN_KEY]["detail"] == {
        "field": SUGGESTION_COOLDOWN_KEY,
        "source": "api",
        "paths": ["/chat", "/goals"],
    }

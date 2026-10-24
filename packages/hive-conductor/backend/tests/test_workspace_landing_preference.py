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

from services import chat_completion, profile_store  # noqa: E402
from services.workspace_preferences import (  # noqa: E402
    LANDING_KEY,
    RESTORE_KEY,
    PreferenceValueError,
    normalize_landing_path,
    normalize_restore_aggressiveness,
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

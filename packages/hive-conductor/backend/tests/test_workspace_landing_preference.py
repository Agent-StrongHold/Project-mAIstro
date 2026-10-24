"""Workspace default landing preference (#1050 first slice).

The preference lives on the canonical user profile so UI, PUT /v1/profile, and
chat ``profile_set`` share one durable owner. Missing or unknown values mean
Workspace Home — never a second browser-local product authority.
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

pytestmark = [pytest.mark.contract("behavioral")]

LANDING_KEY = "workspace_default_landing"


@pytest.fixture(autouse=True)
def _fresh_store() -> Iterator[None]:
    """Every test starts on its own ephemeral store and leaves nothing behind."""
    profile_store.reset()
    yield
    profile_store.reset()


def test_profile_schema_lists_workspace_default_landing() -> None:
    assert LANDING_KEY in chat_completion.PROFILE_SCHEMA["preferences"]


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

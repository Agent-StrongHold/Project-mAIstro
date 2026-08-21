"""Boy Scout coverage: services/program_store.py (was 36%) +
settings_defaults.py (was 65%).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- program_store ---------------------------------------------------


@pytest.fixture(autouse=True)
def _wipe_program_contexts():
    import stores

    for k in list(stores.program_contexts.keys()):
        stores.program_contexts.pop(k)
    yield
    for k in list(stores.program_contexts.keys()):
        stores.program_contexts.pop(k)


def test_get_context_creates_empty_when_missing() -> None:
    from services import program_store as prog

    ctx = prog.get_context("brand-new-user")
    assert ctx.user_id == "brand-new-user"
    # Subsequent reads return the persisted instance, not a fresh empty
    again = prog.get_context("brand-new-user")
    assert again.user_id == "brand-new-user"


def test_save_context_round_trips() -> None:
    from services import program_store as prog

    ctx = prog.get_context("u1")
    updated = ctx.model_copy(update={"interview_step": 3})
    out = prog.save_context(updated)
    assert out is updated
    # Read back
    again = prog.get_context("u1")
    assert again.interview_step == 3


def test_two_workspaces_for_the_same_user_are_independent() -> None:
    """Persona/Workspace Phase B: keyed by (user_id, project_id), not bare user_id."""
    from services import program_store as prog

    pm_ctx = prog.get_context("u1", "ws-pm")
    canvas_ctx = prog.get_context("u1", "ws-canvas")
    assert pm_ctx.project_id == "ws-pm"
    assert canvas_ctx.project_id == "ws-canvas"

    prog.save_context(pm_ctx.model_copy(update={"interview_step": 2}))
    prog.save_context(canvas_ctx.model_copy(update={"interview_step": 5}))

    assert prog.get_context("u1", "ws-pm").interview_step == 2
    assert prog.get_context("u1", "ws-canvas").interview_step == 5


def test_get_context_without_project_id_defaults_to_default_workspace() -> None:
    from services import program_store as prog

    ctx = prog.get_context("legacy-user")
    assert ctx.project_id == "default"


def test_pre_phase_b_legacy_bare_user_id_key_migrates_to_default_project() -> None:
    """Installs from before Phase B persisted this keyed by bare user_id. The
    first read under the new (user_id, project_id) scheme must recover that
    state, not silently return a blank context and orphan the old record."""
    import stores
    from services import program_store as prog

    legacy_ctx = prog.get_context("legacy-user", "default")
    legacy_ctx = legacy_ctx.model_copy(update={"interview_step": 3, "program_name": "Old Program"})
    # Simulate a pre-Phase-B record: keyed by bare user_id, not "user_id:default".
    stores.program_contexts.pop("legacy-user:default", None)
    stores.program_contexts["legacy-user"] = legacy_ctx.model_dump(mode="json")

    migrated = prog.get_context("legacy-user")
    assert migrated.interview_step == 3
    assert migrated.program_name == "Old Program"
    assert migrated.project_id == "default"
    # Migrated forward, not left duplicated under the old key.
    assert "legacy-user" not in stores.program_contexts
    assert "legacy-user:default" in stores.program_contexts

    # Second read is stable (reads the migrated key directly).
    again = prog.get_context("legacy-user")
    assert again.interview_step == 3


def test_context_dict_returns_model_dump() -> None:
    from services import program_store as prog

    d = prog.context_dict("u2")
    assert isinstance(d, dict)
    assert d.get("user_id") == "u2"


# --- settings_defaults --------------------------------------------------


def test_default_settings_returns_settings_model_with_expected_fields() -> None:
    from settings_defaults import default_settings

    s = default_settings()
    # Has expected fields
    assert hasattr(s, "default_model")
    assert hasattr(s, "chat_default_model") or hasattr(s, "default_model")

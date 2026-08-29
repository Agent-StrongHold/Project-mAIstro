"""SettingsModel carries per-slot capability config; PATCH round-trips it (SPEC-184)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app
from models.schemas import CapabilitySetting, SettingsModel


def _config_writer(task_id: str) -> TestClient:
    """A logged-in client with config.write, elevated against `task_id`.

    Settings writes require config.write permission + task-bound elevation
    (middleware/auth.py); mirrors the elevation pattern in test_api.py.
    """
    from datetime import UTC, datetime

    import stores

    from maistro.security.passwords import hash_password

    uid = f"capcfg-{task_id}"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=["config.write"],
        created_at=datetime.now(UTC),
    )
    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": uid, "password": "pw"})
    assert r.status_code == 200, r.text
    e = c.post(
        "/v1/auth/elevate",
        json={"password": "pw", "permissions": ["config.write"], "task_id": task_id},
    )
    assert e.status_code == 200, e.text
    return c


def test_settings_model_has_capabilities_default_empty() -> None:
    assert SettingsModel().capabilities == {}


def test_capability_setting_defaults() -> None:
    cs = CapabilitySetting()
    assert cs.enabled is True
    assert cs.active_provider is None
    assert cs.provider_settings == {}


def test_patch_settings_sets_capabilities() -> None:
    c = _config_writer("cap-task-1")
    body = {
        "capabilities": {
            "infra_action": {"enabled": True, "active_provider": "host_health"},
            "approval": {"enabled": True, "active_provider": "inbox"},
        }
    }
    r = c.patch("/v1/settings", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["capabilities"]["infra_action"]["active_provider"] == "host_health"
    assert data["capabilities"]["approval"]["enabled"] is True

    # Round-trips on GET.
    g = c.get("/v1/settings")
    assert g.json()["capabilities"]["infra_action"]["active_provider"] == "host_health"

    # Stored as validated CapabilitySetting models, not raw dicts (bridge reads these).
    from services import settings_store

    assert isinstance(settings_store.current().capabilities["infra_action"], CapabilitySetting)


def test_patch_without_capabilities_leaves_existing_untouched() -> None:
    c = _config_writer("cap-task-2")
    c.patch("/v1/settings", json={"capabilities": {"approval": {"active_provider": "inbox"}}})
    # A later unrelated patch must not wipe capabilities (exclude_none on the body).
    c.patch("/v1/settings", json={"temperature": 0.5})
    g = c.get("/v1/settings")
    assert g.json()["capabilities"]["approval"]["active_provider"] == "inbox"

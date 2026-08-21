import sys
from pathlib import Path

import pytest

# The backend dir must come FIRST: the monorepo root also has a `services/`
# package (sandbox_broker) that shadows ours when the root pytest.ini's
# `pythonpath = .` wins the sys.path race.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True, scope="session")
def _init_engine() -> None:
    import services.engine as engine_mod
    from adapters.maistro_core import StubAgentPort

    if engine_mod._singleton is None:
        svc = engine_mod.EngineService()
        svc._agent_port = StubAgentPort()
        engine_mod._singleton = svc

    import services.foundation as foundation_mod

    if foundation_mod._singleton is None:
        f = foundation_mod.Foundation()
        foundation_mod._singleton = f

    import stores

    stores.initialize_stores()

    _seed_test_user()

    import tempfile

    from services import user_credentials as cred_svc

    cred_svc.init_credential_store(tempfile.mkdtemp(prefix="hive-cred-test-"))

    # Initialize design render service for tests that need it
    try:
        from services.design_render import init_design_render_service

        init_design_render_service()
    except Exception:
        pass  # Service may not be available in all test environments


@pytest.fixture(autouse=True)
def _isolate_persona_authoring_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect wizard-authored persona templates to tmp_path so tests never
    write YAML files into the developer's real ~/.conductor."""
    import services.persona_authoring as persona_authoring

    monkeypatch.setattr(
        persona_authoring, "user_templates_dir", lambda: tmp_path / "persona_templates"
    )


@pytest.fixture(autouse=True)
def _isolate_dashboard_layouts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect layout persistence to tmp_path so tests never mutate the
    checked-in data/dashboard_layouts.json."""
    import copy

    from routes import dashboard_layout

    monkeypatch.setattr(dashboard_layout, "_DB_PATH", tmp_path / "dashboard_layouts.json")
    snapshot = copy.deepcopy(dashboard_layout._LAYOUTS)
    yield
    dashboard_layout._LAYOUTS.clear()
    dashboard_layout._LAYOUTS.update(snapshot)


def _seed_test_user() -> None:
    import stores

    if len(stores.users) > 0:
        return

    from datetime import UTC, datetime

    now_ts = datetime.now(UTC)
    # Precomputed bcrypt hashes (legacy); login auto-upgrades to Argon2id on success.
    stores.users["user"] = stores.users._model_class(
        id="user",
        username="testuser",
        password_hash="$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq",
        role="user",
        is_active=True,
        permissions=[],
        created_at=now_ts,
    )
    stores.users["admin"] = stores.users._model_class(
        id="admin",
        username="testadmin",
        password_hash="$2b$12$QByl/bXdX8r5UJOGZvS1uelzetMHaGLsRG0hu97dSDIerv2FFdbH.",
        role="admin",
        is_active=True,
        permissions=[],
        created_at=now_ts,
    )


@pytest.fixture(scope="session")
def authed_client():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert r.status_code == 200
    return client


@pytest.fixture(scope="session")
def admin_client():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
    assert r.status_code == 200
    return client


@pytest.fixture(autouse=True)
def _isolate_vault_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect first-run vault provisioning to tmp_path so tests never write
    age keys or vault files into the developer's real ~/.conductor."""
    import routes.setup as setup_routes

    monkeypatch.setattr(
        setup_routes,
        "_vault_paths",
        lambda: (str(tmp_path / "secrets.age"), str(tmp_path / "admin.key")),
    )

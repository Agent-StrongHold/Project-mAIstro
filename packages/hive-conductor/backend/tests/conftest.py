import os
import sys
from pathlib import Path

import pytest

# This suite drives the app over plain HTTP through Starlette's TestClient, so
# it is a local-development context in the exact sense #369 defines one: a
# `Secure` cookie is never sent back over `http://`, and every route test that
# needs a logged-in session would fail with no session rather than with a
# meaningful error.
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
os.environ.setdefault("ALLOW_INSECURE_TRANSPORT", "true")

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

    try:
        from services.design_render import init_design_render_service

        init_design_render_service()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_persona_authoring_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect wizard-authored persona templates to tmp_path."""
    import services.persona_authoring as persona_authoring

    monkeypatch.setattr(
        persona_authoring, "user_templates_dir", lambda: tmp_path / "persona_templates"
    )


@pytest.fixture(autouse=True)
def _isolate_dashboard_layouts():
    """Give each test its own layout store."""
    import copy

    import stores

    snapshot = copy.deepcopy(dict(stores.dashboard_layouts.items()))
    yield
    for key in list(stores.dashboard_layouts.keys()):
        stores.dashboard_layouts.pop(key)
    for key, value in snapshot.items():
        stores.dashboard_layouts[key] = value


@pytest.fixture(autouse=True)
def _isolate_workspace_authority():
    """Do not let the canonical fallback/presentation adapter leak across tests."""
    from services.workspace_authority import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture(autouse=True)
def _legacy_registration_implementation_tests(request: pytest.FixtureRequest):
    """Let legacy implementation tests exercise /register under an open policy.

    Since #313 the shipped route enforces the durable registration policy —
    closed by default — and SecurityHeadersMiddleware no longer short-circuits
    it. A few older password/credential tests are about the *registration
    implementation* (Argon2 storage, audit rows, sessions) rather than the
    policy. For only those named modules, write an `open` policy record for
    the duration of the test and drop it afterwards. Production has no
    bypass: `open` is reachable only through the admin route or setup.
    """
    legacy_modules = {
        "test_api.py",
        "test_auth_password_storage.py",
        "test_credential_security_audit.py",
        "test_credentials_api.py",
    }
    if Path(str(request.fspath)).name not in legacy_modules:
        yield
        return

    from services import registration_policy

    registration_policy.set_mode("open", actor="test:legacy-registration")
    try:
        yield
    finally:
        registration_policy.reset()


@pytest.fixture(autouse=True)
def _route_local_llm_alias_tracks_service_patch(monkeypatch: pytest.MonkeyPatch):
    """Keep older API tests' service-level LLM patches effective after #488."""
    import routes.chat as chat_routes
    import services.chat_completion as chat_service

    monkeypatch.setattr(chat_routes, "build_llm_port", lambda: chat_service.build_llm_port())


def _seed_test_user() -> None:
    import stores

    if len(stores.users) > 0:
        return

    from datetime import UTC, datetime

    now_ts = datetime.now(UTC)
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
    """Redirect first-run vault provisioning to tmp_path."""
    import routes.setup as setup_routes

    monkeypatch.setattr(
        setup_routes,
        "_vault_paths",
        lambda: (str(tmp_path / "secrets.age"), str(tmp_path / "admin.key")),
    )

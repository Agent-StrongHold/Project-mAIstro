import os
import sys
from pathlib import Path

import pytest

# This suite drives the app over plain HTTP through Starlette's TestClient, so
# it is a local-development context in the exact sense #369 defines one: a
# `Secure` cookie is never sent back over `http://`, and every route test that
# needs a logged-in session would fail with no session rather than with a
# meaningful error.
#
# So the suite declares itself, using the same two settings a developer running
# `uvicorn main:app --reload` sets — rather than the production default being
# weakened to suit the tests, which is the arrangement #369 exists to undo.
#
# The production shape is asserted separately and deliberately, by
# `test_session_cookie_policy.py`, which reads `Settings()` directly rather
# than through this environment.
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
def _isolate_dashboard_layouts():
    """Give each test its own layout store.

    There is no file to redirect any more (#340): layouts are a `JsonStore` in
    `stores`, unbacked in tests, so isolation is restoring the dict rather than
    pointing a path at tmp_path.
    """
    import copy

    import stores

    snapshot = copy.deepcopy(dict(stores.dashboard_layouts.items()))
    yield
    for key in list(stores.dashboard_layouts.keys()):
        stores.dashboard_layouts.pop(key)
    for key, value in snapshot.items():
        stores.dashboard_layouts[key] = value


@pytest.fixture(autouse=True)
def _legacy_registration_implementation_tests(request: pytest.FixtureRequest):
    """Let legacy implementation tests exercise /register without reopening it
    for anonymous callers generally.

    A few older password/credential tests are about the *registration
    implementation* rather than anonymous route exposure. Registration is
    closed by default after setup (#313's RegistrationPolicyMiddleware, the
    real production gate); for only those named modules, open the same policy
    an administrator would, through the real service function, and close it
    again after. No bypass flag or backdoor -- this is the production
    mechanism, exercised the way an operator would use it.
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

    from services.registration_policy import set_policy

    set_policy("open")
    try:
        yield
    finally:
        set_policy("closed")


@pytest.fixture(autouse=True)
def _route_local_llm_alias_tracks_service_patch(monkeypatch: pytest.MonkeyPatch):
    """Keep older API tests' service-level LLM patches effective after #488.

    The containment route imports build_llm_port into routes.chat so production
    requests cannot fall back into the tool loop. Some pre-existing tests patch
    services.chat_completion.build_llm_port. Route the test alias through that
    service symbol dynamically so those mocks still test the current route.
    """
    import routes.chat as chat_routes
    import services.chat_completion as chat_service

    monkeypatch.setattr(chat_routes, "build_llm_port", lambda: chat_service.build_llm_port())


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

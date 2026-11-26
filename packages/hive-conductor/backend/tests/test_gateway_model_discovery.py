"""Gateway model discovery — #287.

The Setup wizard must be able to tell a real gateway catalog from a
stored-default substitute: a failed fetch that looks like a valid catalog is
what let a broken or unauthorized gateway pass as configured. These tests pin
the additive discovery metadata on the `/v1/settings/models` surface, the
failure taxonomy it distinguishes, and the `model_availability` verdict the
wizard's final preflight persists with the setup configuration.
"""

from __future__ import annotations

import json
import ssl
from typing import Any

import httpx
import pytest
from routes import settings as settings_routes


class _RecordingStore:
    """Minimal durable store, same shape test_settings_durability uses."""

    def __init__(self) -> None:
        self.writes = 0
        self._document: str | None = None

    @property
    def durable(self) -> bool:
        return True

    def read(self) -> str | None:
        return self._document

    def write(self, document: str) -> None:
        self.writes += 1
        self._document = document


@pytest.fixture
def store() -> Any:
    from services import settings_store

    recording = _RecordingStore()
    settings_store.reset(store=recording)
    yield recording
    settings_store.reset()


def _gateway_env(monkeypatch: pytest.MonkeyPatch, base: str = "http://proxy.invalid/v1") -> None:
    monkeypatch.setenv("LITELLM_API_BASE", base)
    monkeypatch.setenv("LITELLM_API_KEY", "unused-by-the-stub")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)


def _gateway_response(status: int, payload: Any) -> httpx.Response:
    body = json.dumps(payload).encode()
    request = httpx.Request("GET", "http://proxy.invalid/v1/models")
    return httpx.Response(status, content=body, request=request)


def _save_default() -> None:
    from models.schemas import SettingsModel
    from services import settings_store

    settings_store.save(SettingsModel(default_model="stored-default"))


# --- the catalog is honest about where it came from -----------------------


def test_no_configured_gateway_is_not_configured_not_discovered(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_default()
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)

    out = settings_routes.settings_models()

    assert out["models"] == ["stored-default"]
    assert out["discovered"] is False
    assert out["source"] == "stored_default"
    assert out["error"]["kind"] == "not_configured"


def test_a_gateway_answer_is_marked_discovered(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_default()
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx,
        "get",
        lambda *a, **k: _gateway_response(
            200, {"data": [{"id": "b"}, {"id": "a"}, {"model": "c"}, {"id": ""}]}
        ),
    )

    out = settings_routes.settings_models()

    assert out["models"] == ["a", "b", "c"]
    assert out["discovered"] is True
    assert out["source"] == "gateway"
    assert out["error"] is None


# --- every failure class is distinguishable -------------------------------


def _assert_failure_kind(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    source: str = "stored_default",
    models: list[str] | None = None,
) -> dict:
    _save_default()
    out = settings_routes.settings_models()
    assert out["discovered"] is False
    assert out["source"] == source
    assert out["models"] == (["stored-default"] if models is None else models)
    assert out["error"]["kind"] == kind
    assert out["error"]["message"]
    return out


def test_http_401_is_auth(monkeypatch: pytest.MonkeyPatch, store: _RecordingStore) -> None:
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx, "get", lambda *a, **k: _gateway_response(401, {"detail": "nope"})
    )
    _assert_failure_kind(monkeypatch, "auth")


def test_http_404_is_not_found(monkeypatch: pytest.MonkeyPatch, store: _RecordingStore) -> None:
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx, "get", lambda *a, **k: _gateway_response(404, {"detail": "gone"})
    )
    _assert_failure_kind(monkeypatch, "not_found")


def test_http_5xx_is_server(monkeypatch: pytest.MonkeyPatch, store: _RecordingStore) -> None:
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx, "get", lambda *a, **k: _gateway_response(503, {"detail": "down"})
    )
    _assert_failure_kind(monkeypatch, "server")


def test_connection_errors_are_connectivity(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    _gateway_env(monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(settings_routes.httpx, "get", _boom)
    _assert_failure_kind(monkeypatch, "connectivity")


def test_timeouts_are_connectivity(monkeypatch: pytest.MonkeyPatch, store: _RecordingStore) -> None:
    _gateway_env(monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(settings_routes.httpx, "get", _boom)
    _assert_failure_kind(monkeypatch, "connectivity")


def test_certificate_failures_are_tls(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    _gateway_env(monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> None:
        exc = httpx.ConnectError("handshake failed")
        exc.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
        raise exc

    monkeypatch.setattr(settings_routes.httpx, "get", _boom)
    _assert_failure_kind(monkeypatch, "tls")


def test_disallowed_url_schemes_are_policy(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    # No httpx stub: an unsupported scheme is rejected by httpx itself before
    # any network I/O, which is exactly the policy class.
    _save_default()
    _gateway_env(monkeypatch, base="ftp://proxy.invalid/v1")
    _assert_failure_kind(monkeypatch, "policy")


def test_non_json_bodies_are_malformed(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    _gateway_env(monkeypatch)
    request = httpx.Request("GET", "http://proxy.invalid/v1/models")
    monkeypatch.setattr(
        settings_routes.httpx,
        "get",
        lambda *a, **k: httpx.Response(200, content=b"<html>not json</html>", request=request),
    )
    _assert_failure_kind(monkeypatch, "malformed")


def test_wrong_shapes_are_malformed(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    for payload in ({"data": "nope"}, {"nope": True}, {"data": ["a-string-entry"]}):
        _gateway_env(monkeypatch)
        monkeypatch.setattr(
            settings_routes.httpx,
            "get",
            lambda *a, _p=payload, **k: _gateway_response(200, _p),
        )
        _assert_failure_kind(monkeypatch, "malformed")


def test_an_empty_catalog_is_its_own_state(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingStore
) -> None:
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx, "get", lambda *a, **k: _gateway_response(200, {"data": []})
    )
    # An empty gateway catalog is reported as the gateway's (empty) answer,
    # not substituted: the caller must see that the gateway said "nothing"
    # (source="gateway", models=[]) rather than a stored-default stand-in.
    _assert_failure_kind(monkeypatch, "empty", source="gateway", models=[])


# --- the back-compat list view keeps its contract --------------------------


def test_the_list_view_still_falls_back_to_the_stored_default(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_default()
    _gateway_env(monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no proxy here")

    monkeypatch.setattr(settings_routes.httpx, "get", _boom)

    assert settings_routes._fetch_available_models() == ["stored-default"]


def test_the_list_view_returns_a_discovered_catalog_sorted(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_default()
    _gateway_env(monkeypatch)
    monkeypatch.setattr(
        settings_routes.httpx,
        "get",
        lambda *a, **k: _gateway_response(200, {"data": [{"id": "b"}, {"id": "a"}]}),
    )

    assert settings_routes._fetch_available_models() == ["a", "b"]


# --- the wizard's final preflight verdict is persisted ---------------------


class TestSetupRecordsModelAvailability:
    """`model_availability` (#287) lands in the persisted setup config."""

    @staticmethod
    def _fresh_instance(monkeypatch: pytest.MonkeyPatch) -> None:
        import stores
        from models.schemas import HiveAccount
        from routes import setup as setup_routes
        from services.model_store import JsonStore, ModelStore

        monkeypatch.setattr(stores, "users", ModelStore("users", HiveAccount))
        monkeypatch.setattr(stores, "username_claims", JsonStore("username_claims"))
        monkeypatch.setattr(setup_routes, "_get_kv", lambda: None)

    def test_an_explicit_unverified_verdict_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from routes.setup import complete_setup

        self._fresh_instance(monkeypatch)

        out = complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "disc-admin",
                "admin_password": "s3cret-admin",
                "user_username": "disc-user",
                "user_password": "s3cret-user",
                "default_model": "some-model",
                "model_availability": "unverified",
            }
        )

        assert out["setup_complete"] is True
        assert out["config"]["model_availability"] == "unverified"

    def test_a_verified_verdict_is_persisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from routes.setup import complete_setup

        self._fresh_instance(monkeypatch)

        out = complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "disc-admin2",
                "admin_password": "s3cret-admin",
                "user_username": "disc-user2",
                "user_password": "s3cret-user",
                "model_availability": "verified",
            }
        )

        assert out["config"]["model_availability"] == "verified"

    def test_callers_that_predates_the_field_make_no_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from routes.setup import complete_setup

        self._fresh_instance(monkeypatch)

        out = complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "disc-admin3",
                "admin_password": "s3cret-admin",
                "user_username": "disc-user3",
                "user_password": "s3cret-user",
            }
        )

        assert "model_availability" not in out["config"]

    def test_unknown_availability_values_are_rejected(self) -> None:
        from routes.setup import SetupCompleteBody

        with pytest.raises(ValueError):
            SetupCompleteBody.model_validate(
                {
                    "hardware_preset": "auto",
                    "admin_password": "s3cret-admin",
                    "user_password": "s3cret-user",
                    "model_availability": "trust-me",
                }
            )

"""`/v1/voice/` is no longer public, and its device key is a control (#316).

There were no tests for voice at all before this, which is part of how the
prefix stayed in `_PUBLIC_PREFIXES` for the whole of the repository's history:
nothing ever asked what an anonymous caller got.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from main import app  # noqa: E402

# Assembled from pieces so no single line reads as `KEY = "<secret>"`.
# `.gitleaks.toml` deliberately refuses allowlists for findings in code — the
# repository's rule is to split the literal — and a fake credential that trips
# a secret scanner still costs a CI cycle and a reviewer's attention to
# dismiss.
DEVICE_KEY = "voice-device-" + "316-" + "not-a-real-credential"
ROTATED_KEY = "voice-device-" + "316-" + "also-not-a-real-one"

SATELLITE_ACCOUNT = "kitchen-satellite"
SATELLITE_ID = "user-voice-316"

INTENT = "/v1/voice/intent"
UTTERANCE: dict[str, Any] = {"text": "turn the kitchen light on", "room": "kitchen"}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """The credential is read through `get_settings`, which is cached."""
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def account() -> str:
    """The ordinary user account the satellite acts as."""
    stores.users[SATELLITE_ID] = stores.users._model_class(
        id=SATELLITE_ID,
        username=SATELLITE_ACCOUNT,
        password_hash="",
        role="user",
        is_active=True,
        permissions=[],
        created_at=datetime.now(UTC),
    )
    yield SATELLITE_ACCOUNT
    stores.users.pop(SATELLITE_ID, None)


@pytest.fixture
def configured(account: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A deployment with the voice credential set up."""
    from config import get_settings

    monkeypatch.setenv("VOICE_SERVICE_KEY", DEVICE_KEY)
    monkeypatch.setenv("VOICE_SERVICE_ACCOUNT", account)
    get_settings.cache_clear()
    return DEVICE_KEY


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Answer the utterance without a real model. Records the contained request.

    Voice has two construction paths: the normal build_llm_port path and a
    direct HTTP adapter when LiteLLM base/key settings are present. Stub both so
    developer environment or .env credentials can never turn this test into a
    network call.
    """
    captured: dict[str, Any] = {}

    class FakeLLM:
        async def complete(self, req):
            captured["messages"] = req.messages
            captured["tools"] = req.tools
            return {"choices": [{"message": {"role": "assistant", "content": "on it"}}]}

    monkeypatch.setattr("routes.voice.build_llm_port", lambda: FakeLLM(), raising=False)
    monkeypatch.setattr(
        "adapters.llm_http.HttpOpenAIProtocolLLM",
        lambda **_kwargs: FakeLLM(),
    )
    return captured


def _client() -> TestClient:
    return TestClient(app)


class TestThePrefixIsNoLongerPublic:
    def test_an_anonymous_request_is_refused(self) -> None:
        """The whole issue in one assertion. This was a 200 (or, since the
        route's own call could not succeed, a 500) — either way it ran."""
        assert _client().post(INTENT, json=UTTERANCE).status_code == 401

    def test_an_anonymous_request_is_refused_even_when_voice_is_configured(
        self, configured: str
    ) -> None:
        assert _client().post(INTENT, json=UTTERANCE).status_code == 401

    def test_a_made_up_bearer_token_is_refused(self, configured: str) -> None:
        response = _client().post(
            INTENT, json=UTTERANCE, headers={"Authorization": "Bearer not-the-key"}
        )

        assert response.status_code == 401

    def test_the_prefix_is_absent_from_the_public_list(self) -> None:
        """Belt and braces on the declaration itself, because the route-level
        assertions above would also pass if voice simply stopped existing."""
        from middleware.auth import _PUBLIC_EXACT, _PUBLIC_PREFIXES, _PUBLIC_PREFIXES_LOOSE

        every = (*_PUBLIC_PREFIXES, *_PUBLIC_PREFIXES_LOOSE, *_PUBLIC_EXACT)

        assert not [path for path in every if "voice" in path]


class TestAnUnsetKeyDoesNotMakeTheRouteOpen:
    """The precise failure of the check this replaces: its first line was
    `if not VOICE_API_KEY: return`, so the shipped default was 'no key, no
    check, everyone in'."""

    def test_no_key_and_no_account_refuses_rather_than_admits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import get_settings

        monkeypatch.delenv("VOICE_SERVICE_KEY", raising=False)
        monkeypatch.delenv("VOICE_SERVICE_ACCOUNT", raising=False)
        get_settings.cache_clear()

        response = _client().post(
            INTENT, json=UTTERANCE, headers={"Authorization": f"Bearer {DEVICE_KEY}"}
        )

        assert response.status_code == 401

    def test_a_key_with_no_account_refuses(
        self, monkeypatch: pytest.MonkeyPatch, account: str
    ) -> None:
        """Half-configured is not configured. A key that names nobody cannot
        produce a principal, and a principal is what authorises the tool loop."""
        from config import get_settings
        from services.voice_identity import configured_credential

        monkeypatch.setenv("VOICE_SERVICE_KEY", DEVICE_KEY)
        monkeypatch.delenv("VOICE_SERVICE_ACCOUNT", raising=False)
        get_settings.cache_clear()

        assert configured_credential() is None

    def test_an_account_with_no_key_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import get_settings
        from services.voice_identity import configured_credential

        monkeypatch.delenv("VOICE_SERVICE_KEY", raising=False)
        monkeypatch.setenv("VOICE_SERVICE_ACCOUNT", SATELLITE_ACCOUNT)
        get_settings.cache_clear()

        assert configured_credential() is None


class TestTheCredentialResolvesToARealAccount:
    def test_the_right_key_reaches_the_route_as_that_user(
        self, configured: str, no_llm: dict[str, Any]
    ) -> None:
        response = _client().post(
            INTENT, json=UTTERANCE, headers={"Authorization": f"Bearer {configured}"}
        )

        assert response.status_code == 200
        assert response.json()["actions_taken"] == []
        assert no_llm["tools"] is None

    def test_the_utterance_and_its_room_reach_the_model(
        self, configured: str, no_llm: dict[str, Any]
    ) -> None:
        _client().post(INTENT, json=UTTERANCE, headers={"Authorization": f"Bearer {configured}"})

        prompt = no_llm["messages"][0]["content"]
        assert "turn the kitchen light on" in prompt
        assert "kitchen" in prompt

    def test_an_account_that_does_not_exist_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import get_settings
        from services.voice_identity import principal_for

        monkeypatch.setenv("VOICE_SERVICE_KEY", DEVICE_KEY)
        monkeypatch.setenv("VOICE_SERVICE_ACCOUNT", "nobody-by-that-name")
        get_settings.cache_clear()

        assert principal_for(f"Bearer {DEVICE_KEY}") is None

    def test_a_disabled_account_refuses(self, configured: str) -> None:
        """Disabling the account the satellite speaks as has to take the
        satellite offline too, or 'disabled' means less than it says."""
        from services.voice_identity import principal_for

        stored = stores.users[SATELLITE_ID]
        stores.users[SATELLITE_ID] = stored.model_copy(update={"is_active": False})

        assert principal_for(f"Bearer {configured}") is None

    def test_the_device_carries_no_task_elevation(self, configured: str) -> None:
        """The key is an identity, not a permission: everything behind
        `_PROTECTED_OPS` stays refused for it."""
        from services.voice_identity import principal_for

        principal = principal_for(f"Bearer {configured}")

        assert principal is not None
        assert principal["elevated_permissions"] == []
        assert principal["elevated_tasks"] == []


class TestTheKeyOpensVoiceAndNothingElse:
    @pytest.mark.parametrize(
        "path",
        ["/v1/chat/sessions", "/v1/agents", "/v1/settings", "/v1/workspaces"],
    )
    def test_the_device_key_is_refused_on_other_surfaces(self, configured: str, path: str) -> None:
        """One key that opened the whole API would be a second front door with
        no session expiry and no per-user authorization behind it."""
        response = _client().get(path, headers={"Authorization": f"Bearer {configured}"})

        assert response.status_code == 401


class TestTheComparisonAndTheReading:
    def test_the_key_is_compared_in_constant_time(
        self, configured: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserted by observing the call rather than by reading the source:
        #320 is open precisely because source-inspection tests do not survive a
        refactor that keeps the text and loses the property."""
        import services.voice_identity as voice_identity

        seen: list[tuple[str, str]] = []

        def spy(a: str, b: str) -> bool:
            seen.append((a, b))
            return a == b

        monkeypatch.setattr(voice_identity, "secret_equal", spy)
        voice_identity.principal_for(f"Bearer {configured}")

        assert seen == [(DEVICE_KEY, DEVICE_KEY)]

    def test_a_rotated_key_takes_effect_without_reimporting(
        self, configured: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The old check read the key into a module constant at import, so no
        reconfiguration could reach it while the process lived."""
        from config import get_settings
        from services.voice_identity import principal_for

        assert principal_for(f"Bearer {DEVICE_KEY}") is not None

        monkeypatch.setenv("VOICE_SERVICE_KEY", ROTATED_KEY)
        get_settings.cache_clear()

        assert principal_for(f"Bearer {DEVICE_KEY}") is None
        assert principal_for(f"Bearer {ROTATED_KEY}") is not None

    @pytest.mark.parametrize(
        "header",
        [None, "", "Bearer ", "Basic abc", DEVICE_KEY, "bearer " + DEVICE_KEY],
    )
    def test_only_a_well_formed_bearer_header_is_read(
        self, configured: str, header: str | None
    ) -> None:
        """Including the lowercase `bearer`: accepting it would be harmless
        here, but the token is only ever produced by our own device config, so
        the narrow reading is the one that cannot surprise anyone."""
        from services.voice_identity import principal_for

        assert principal_for(header) is None

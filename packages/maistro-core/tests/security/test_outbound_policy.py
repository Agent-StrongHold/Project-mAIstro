"""Every outbound surface is guarded at the seam (#155, ADR-082326-5386).

#154's validator was effective and reached three of twenty-five modules,
because it was a function each call site had to remember to call. These tests
hold the property that replaced it: the guard is at the transport, so a module
is covered by routing through the shared pool rather than by remembering.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from maistro.http import (
    aclose_shared_clients,
    get_shared_client,
    override_transport,
    shared_client,
)
from maistro.security.outbound import (
    GuardedTransport,
    OutboundBlockedError,
    OutboundPolicy,
    configure_outbound_policy,
    configured_endpoints,
    current_outbound_policy,
    guarded,
    outbound_origin,
    reset_outbound_policy,
)
from maistro.security.ssrf import SSRFBlockedError


@pytest.fixture(autouse=True)
async def _clean_policy():
    reset_outbound_policy()
    await aclose_shared_clients()
    yield
    reset_outbound_policy()
    await aclose_shared_clients()


class _Recording(httpx.AsyncBaseTransport):
    """A real-looking transport that records what reached it and answers 200."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(str(request.url))
        return httpx.Response(200, request=request)

    async def aclose(self) -> None:
        return None


class _Answering(httpx.AsyncBaseTransport):
    """A real-looking transport that delegates to a handler, like `_Recording`.

    Deliberately not `httpx.MockTransport`: `guarded()` returns that one
    unwrapped, so a test built on it never reaches the policy at all.
    """

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)

    async def aclose(self) -> None:
        return None


async def _get(url: str, transport: httpx.AsyncBaseTransport, **kwargs) -> httpx.Response:
    async with shared_client(timeout=5.0, transport=transport, **kwargs) as client:
        return await client.get(url)


# --- the seam covers what call sites forgot -------------------------------


@pytest.mark.ac("ADR-082326-5386/AC-2")
async def test_a_private_target_is_refused_at_the_transport() -> None:
    inner = _Recording()

    with pytest.raises(SSRFBlockedError):
        await _get("http://127.0.0.1:8080/admin", inner)

    assert inner.seen == [], "the request reached the transport before being checked"


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # IMDS, v4
        "http://[::ffff:169.254.169.254]/latest/",  # the same, spelled v6
        "http://2852039166/",  # 169.254.169.254 as an integer
        "http://0x7f000001/",  # 127.0.0.1 in hex
        "http://127.1/",  # short-form loopback
        "http://localhost:4000/v1/chat",  # by name
        "http://[::1]:8080/",  # v6 loopback
        "http://0.0.0.0:80/",  # unspecified
        "file:///etc/passwd",  # not an http(s) scheme at all
    ],
)
@pytest.mark.ac("ADR-082326-5386/AC-2")
async def test_the_usual_spellings_all_fail_closed(url: str) -> None:
    inner = _Recording()

    with pytest.raises(SSRFBlockedError):
        await _get(url, inner)

    assert inner.seen == []


async def test_a_public_target_is_reached() -> None:
    """The guard must not refuse ordinary traffic."""
    inner = _Recording()

    response = await _get("https://example.com/x", inner)

    assert response.status_code == 200
    assert inner.seen == ["https://example.com/x"]


# --- redirects ------------------------------------------------------------


@pytest.mark.ac("ADR-082326-5386/AC-3")
async def test_a_redirect_into_a_private_target_is_refused_at_that_hop() -> None:
    """The reason the policy is at the transport rather than at the wrapper."""

    class _Redirector(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.seen.append(str(request.url))
            if request.url.host == "example.com":
                return httpx.Response(
                    302,
                    headers={"Location": "http://169.254.169.254/latest/meta-data/"},
                    request=request,
                )
            return httpx.Response(200, request=request)

    inner = _Redirector()

    with pytest.raises(SSRFBlockedError):
        await _get("https://example.com/start", inner, follow_redirects=True)

    # The first hop was allowed and made; the second never reached the wire.
    assert inner.seen == ["https://example.com/start"]


# --- allowances -----------------------------------------------------------


@pytest.mark.ac("ADR-082326-5386/AC-4")
async def test_a_configured_gateway_is_reachable_without_disabling_the_guard() -> None:
    inner = _Recording()
    configure_outbound_policy("http://127.0.0.1:4000")

    response = await _get("http://127.0.0.1:4000/v1/chat/completions", inner)

    assert response.status_code == 200
    # And nothing else on that host became reachable with it.
    with pytest.raises(SSRFBlockedError):
        await _get("http://127.0.0.1:8080/admin", inner)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/",  # different port
        "https://127.0.0.1:4000/",  # different scheme
        "http://127.0.0.2:4000/",  # different host
        "http://10.0.0.5:4000/",  # another private address entirely
    ],
)
@pytest.mark.ac("ADR-082326-5386/AC-5")
async def test_an_allowance_does_not_widen_beyond_what_it_names(url: str) -> None:
    inner = _Recording()
    configure_outbound_policy("http://127.0.0.1:4000")

    with pytest.raises(SSRFBlockedError):
        await _get(url, inner)


async def test_allowances_accumulate_rather_than_replace() -> None:
    """Two wiring sites configure endpoints; neither may revoke the other."""
    configure_outbound_policy("http://127.0.0.1:4000")
    configure_outbound_policy("http://homeassistant.local:8123")

    policy = current_outbound_policy()

    assert policy.allows("http://127.0.0.1:4000/v1")
    assert policy.allows("http://homeassistant.local:8123/api/states")


def test_the_default_port_is_the_same_origin_written_out() -> None:
    policy = OutboundPolicy().with_origins(["http://gateway.internal"])

    assert policy.allows("http://gateway.internal:80/x")
    assert not policy.allows("http://gateway.internal:8080/x")


def test_an_origin_ignores_path_query_and_userinfo() -> None:
    assert outbound_origin("https://u:p@host.example:443/a?b=c#d") == "https://host.example:443"
    assert outbound_origin("HTTPS://HOST.EXAMPLE/x") == "https://host.example:443"


def test_a_malformed_port_matches_no_allowance() -> None:
    """It must fall through to validation rather than accidentally matching."""
    policy = OutboundPolicy().with_origins(["http://host.example:80"])

    assert not policy.allows("http://host.example:notaport/")


def test_empty_endpoints_are_ignored_when_seeding() -> None:
    policy = OutboundPolicy().with_origins(["", "   ", "http://real.example:9000"])

    assert policy.origins == frozenset({"http://real.example:9000"})


# --- seeding --------------------------------------------------------------


@pytest.mark.ac("ADR-082326-5386/AC-4")
def test_endpoints_are_read_off_the_settings_not_listed_here() -> None:
    class _LiteLLM:
        base_url = "http://litellm.internal:4000"

    class _Ntfy:
        base_url = ""

    class _Settings:
        litellm = _LiteLLM()
        ntfy = _Ntfy()
        ollama_base_url = "http://127.0.0.1:11434/v1"

    origins = OutboundPolicy().with_origins(configured_endpoints(_Settings())).origins

    assert origins == frozenset({"http://litellm.internal:4000", "http://127.0.0.1:11434"})


def test_seeding_tolerates_a_settings_object_missing_every_field() -> None:
    assert configured_endpoints(object()) == ["", "", "", "", "", ""]


# --- what is and is not wrapped -------------------------------------------


@pytest.mark.ac("ADR-082326-5386/AC-1")
def test_a_pooled_client_gets_a_guarded_transport() -> None:
    client = get_shared_client(timeout=1.0)

    assert isinstance(client._transport, GuardedTransport)  # type: ignore[attr-defined]


def test_a_response_faking_transport_is_left_alone() -> None:
    """It opens no socket, and it is how the suite avoids the network."""
    mock = httpx.MockTransport(lambda r: httpx.Response(200))

    assert guarded(mock) is mock


@pytest.mark.ac("ADR-082326-5386/AC-1")
def test_wrapping_twice_does_not_stack() -> None:
    once = guarded(_Recording())

    assert guarded(once) is once


# --- the two caller-influenced call sites, by name ------------------------
#
# #155 names these two because their destination is chosen by a caller rather
# than by an operator. Testing the seam in the abstract does not prove they
# reach it: `progress_webhook` built its own `httpx.AsyncClient` and so was
# outside the pool entirely until this change.


@pytest.mark.ac("ADR-082326-5386/AC-6")
async def test_the_progress_webhook_cannot_post_to_a_private_target() -> None:
    from maistro.tasks.progress_webhook import ConductorProgressPayload, ProgressWebhookNotifier

    inner = _Recording()
    notifier = ProgressWebhookNotifier(
        post_url="http://169.254.169.254/latest/",
        client=httpx.AsyncClient(transport=guarded(inner)),
    )

    # `notify` swallows failures by design — a webhook must not fail a task —
    # so the evidence is that nothing reached the transport.
    await notifier.notify(ConductorProgressPayload(task_id="t-1", status="coding"))

    assert inner.seen == []


async def test_the_progress_webhook_uses_the_pool_so_it_is_guarded() -> None:
    """It built its own client, so the seam did not reach it at all."""
    from maistro.tasks.progress_webhook import ProgressWebhookNotifier

    notifier = ProgressWebhookNotifier(post_url="https://hooks.example/x")

    transport = notifier._client._transport  # type: ignore[attr-defined]
    assert isinstance(transport, GuardedTransport)


@pytest.mark.ac("ADR-082326-5386/AC-6")
async def test_the_http_tool_executor_cannot_reach_a_private_target() -> None:
    from maistro.agents.strategies.tool_http import HTTPToolExecutor

    executor = HTTPToolExecutor(base_url="http://127.0.0.1:8300")

    result = await executor.call("run_tests", {})

    # It reports errors as strings rather than raising, so the refusal shows up
    # in what it returns.
    assert result.startswith("Error")
    assert "127.0.0.1" in result or "blocked" in result.lower()


async def test_the_ntfy_client_uses_the_pool_so_it_is_guarded() -> None:
    from maistro.integrations.ntfy import NtfyClient

    client = NtfyClient(base_url="https://ntfy.example", default_topic="t")

    transport = client._client._transport  # type: ignore[attr-defined]
    assert isinstance(transport, GuardedTransport)


# --- proxy mounts keep working, and are guarded too ------------------------
#
# The first draft of this seam passed `transport=guarded(...)` to
# `httpx.AsyncClient`. httpx 0.28.1 reads `allow_env_proxies = trust_env and
# transport is None`, so that argument switched environment-proxy support off
# for the whole engine: a deployment egressing through `HTTPS_PROXY` would have
# lost outbound connectivity entirely. These pin the fix in both directions —
# the mounts exist, and they are guarded.


def test_env_proxy_mounts_survive_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    client = get_shared_client(timeout=1.0)

    patterns = [p.pattern for p in client._mounts]  # type: ignore[attr-defined]

    assert "https://" in patterns, f"environment proxy mounts were dropped: {patterns}"


@pytest.mark.ac("ADR-082326-5386/AC-1")
def test_every_proxy_mount_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    client = get_shared_client(timeout=1.0)

    mounted = [t for t in client._mounts.values() if t is not None]  # type: ignore[attr-defined]
    assert mounted, "expected at least one proxy transport to guard"
    assert all(isinstance(t, GuardedTransport) for t in mounted)


def test_httpx_still_exposes_the_transports_this_guards() -> None:
    """An upgrade that renames these must fail here, not silently un-guard.

    `_guard_built_transports` reaches into two private attributes because the
    public constructor cannot express "build your own proxy mounts, then let me
    wrap them". That is a deliberate trade, and this is the alarm on it.
    """
    client = get_shared_client(timeout=1.0)

    assert isinstance(getattr(client, "_transport", None), httpx.AsyncBaseTransport)
    assert isinstance(getattr(client, "_mounts", None), dict)


# --- a refusal is catchable by the handlers already on the path ------------


async def test_a_refusal_is_an_httpx_transport_error() -> None:
    """Callers catch what a client is documented to raise.

    The OAuth token exchange wraps `httpx.HTTPError` into `OAuthExchangeError`,
    the HTTP harness turns `httpx.TransportError` into `HarnessUnavailableError`
    and falls back, and the quota CLI maps it to an exit code. A `ToolError`
    from inside the transport walked past all three.
    """
    inner = _Recording()

    with pytest.raises(httpx.TransportError):
        await _get("http://169.254.169.254/latest/meta-data/", inner)

    assert inner.seen == []


async def test_a_refusal_is_still_an_ssrf_blocked_error() -> None:
    """The dual contract is additive — nothing that caught it before stops."""
    with pytest.raises(SSRFBlockedError):
        await _get("http://169.254.169.254/", _Recording())


async def test_a_refusal_carries_the_request_httpx_promises() -> None:
    with pytest.raises(OutboundBlockedError) as caught:
        await _get("http://127.0.0.1:9/", _Recording())

    assert caught.value.request.url.host == "127.0.0.1"


def test_the_dual_contract_error_reports_both_ancestries() -> None:
    err = OutboundBlockedError("blocked")

    assert isinstance(err, SSRFBlockedError)
    assert isinstance(err, httpx.HTTPError)
    assert err.detail == "blocked"


# --- endpoints that live in a constructor, not in settings -----------------


async def test_home_assistant_registers_its_own_url() -> None:
    """Its URL is a constructor argument defaulting to `http://localhost:8123`.

    Nothing in settings names it, so without the registration in `__init__`
    every real Home Assistant call is refused — and `MockTransport` hides that
    from the rest of the suite, which is how it went unnoticed.
    """
    from maistro.integrations.home_assistant import HomeAssistantIntegration

    HomeAssistantIntegration()

    assert current_outbound_policy().allows("http://localhost:8123/api/states")


async def test_home_assistant_reaches_its_configured_host_through_the_guard() -> None:
    from maistro.integrations.home_assistant import HomeAssistantIntegration

    seen: list[str] = []

    def _answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[], request=request)

    integration = HomeAssistantIntegration(url="http://10.0.0.7:8123", token="t")

    # A *real* transport, not `MockTransport` — the guard leaves that one
    # unwrapped, which is exactly why the suite could not see this refusal.
    with override_transport(_Answering(_answer)):
        await integration.get_states()

    assert seen == ["http://10.0.0.7:8123/api/states"]


def test_an_oauth_provider_registers_its_issuer() -> None:
    """A self-hosted issuer is an RFC1918 address that settings never saw."""
    from maistro.auth.oauth import InMemoryStateStore, OAuth2Client, OAuthProviderConfig

    OAuth2Client(
        providers={
            "keycloak": OAuthProviderConfig(
                name="keycloak",
                authorization_url="https://10.1.2.3:8443/realms/m/protocol/openid-connect/auth",
                token_url="https://10.1.2.3:8443/realms/m/protocol/openid-connect/token",
                client_id="maistro",
                jwks_url="https://10.1.2.3:8443/realms/m/protocol/openid-connect/certs",
            )
        },
        state_store=InMemoryStateStore(),
        http=get_shared_client(timeout=1.0),
        secret_resolver=lambda _name: "secret",
    )

    policy = current_outbound_policy()
    assert policy.allows("https://10.1.2.3:8443/realms/m/protocol/openid-connect/token")
    assert not policy.allows("https://10.1.2.3:9443/anything")


def test_the_progress_webhook_endpoint_is_seeded_from_settings() -> None:
    """It is configured beside the LLM base and is just as likely to be local."""

    class _Settings:
        task_progress_webhook_url = "http://10.9.9.9:8080/progress"

    origins = OutboundPolicy().with_origins(configured_endpoints(_Settings())).origins

    assert origins == frozenset({"http://10.9.9.9:8080"})

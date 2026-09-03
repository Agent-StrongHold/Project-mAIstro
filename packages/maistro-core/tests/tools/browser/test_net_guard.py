"""The browser transport is governed by the canonical outbound policy (#855).

`BrowserClient` used to validate only the URL a caller named — and for
`search_web`, nothing at all — before handing an autonomous browser-use
Agent a live Chromium. These tests hold the property that replaced that:
every network request the browser context makes — the navigation the task
named, the redirect hop that follows it, the subresource the page pulls
in, the destination the model invents mid-run — passes a route handler
that applies the same policy ordinary HTTP effects answer to
(ADR-082326-5386), *before* the network stack connects.

The transport is `tests/tools/browser/fakes.py`'s controlled context: real
guard, real policy, fake wire. Denials are observed as the abort Chromium
would receive; allowances as the continue it would receive.
"""

from __future__ import annotations

import pytest

from maistro.security.outbound import (
    OutboundPolicy,
    configure_outbound_policy,
    current_outbound_policy,
    reset_outbound_policy,
)
from maistro.security.ssrf import (
    BLOCK_INTERNAL_ADDRESS,
    BLOCK_INTERNAL_HOSTNAME,
    BLOCK_SCHEME,
)
from maistro.tools.browser.guard import (
    ABORT_REASON,
    ALLOWED,
    DENIED,
    ROUTE_PATTERN,
    BrowserNetworkGuard,
)

from .fakes import FakePwContext

# A public host these tests can resolve without a socket. The existing
# outbound-policy suite leans on the same fact.
_PUBLIC = "https://example.com/page"


@pytest.fixture(autouse=True)
def _clean_policy() -> None:
    reset_outbound_policy()


async def _guarded_context(**kwargs) -> tuple[BrowserNetworkGuard, FakePwContext]:
    guard = BrowserNetworkGuard(**kwargs)
    context = FakePwContext()
    await guard.attach(context)
    return guard, context


# --- every navigation answers to the policy --------------------------------


@pytest.mark.ac("#855/AC-1")
async def test_a_public_navigation_is_allowed_onto_the_network() -> None:
    _guard, context = await _guarded_context()

    route = await context.navigate(_PUBLIC)

    assert route.action == ("continue",)


@pytest.mark.ac("#855/AC-3")
async def test_a_navigation_the_model_invented_is_governed_too() -> None:
    """The autonomous case: nothing in any task named this destination.

    The route layer cannot tell a task-chosen navigation from a
    model-invented one, and must not need to — that is the point of
    enforcing at the transport instead of at the call site.
    """
    _guard, context = await _guarded_context()

    route = await context.navigate("http://127.0.0.1:8080/admin")

    assert route.action == ("abort", ABORT_REASON)


@pytest.mark.ac("#855/AC-5")
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/admin",
        "http://localhost:4000/v1/chat",
        "http://0x7f000001/",  # 127.0.0.1 in hex
        "http://2130706433/",  # 127.0.0.1 as an integer
        "http://127.1/",  # short-form loopback
        "http://[::1]:8080/",  # v6 loopback
        "http://0.0.0.0/",  # unspecified
        "http://10.0.0.5/",  # RFC1918
        "http://192.168.1.10/",  # RFC1918
        "http://172.16.9.9/",  # RFC1918
        "http://169.254.169.254/latest/meta-data/",  # IMDS
        "http://[::ffff:169.254.169.254]/latest/",  # IMDS, spelled v6
        "http://metadata.google.internal/computeMetadata/v1/",  # by name
        "http://kubernetes.default.svc/api",  # in-cluster name
        "http://[fe80::1]/",  # v6 link-local
        "http://[fd00::1]/",  # v6 ULA
        "file:///etc/passwd",  # not http(s) at all
        "gopher://127.0.0.1:70/x",  # a scheme nobody reasoned about
        "http://",  # no host
    ],
)
async def test_every_notation_of_a_private_or_dangerous_target_is_denied(url: str) -> None:
    guard, context = await _guarded_context()

    route = await context.navigate(url)

    assert route.action == ("abort", ABORT_REASON)
    assert guard.denied_events(), "a refusal without an audit event is unauditable"


@pytest.mark.ac("#855/AC-2")
async def test_a_redirect_hop_from_public_to_private_is_denied_at_that_hop() -> None:
    """Start public, land private: the hop that matters is the one refused."""
    guard, context = await _guarded_context()

    first = await context.navigate(_PUBLIC)
    hop = await context.navigate("http://169.254.169.254/latest/meta-data/iam")

    assert first.action == ("continue",)
    assert hop.action == ("abort", ABORT_REASON)
    decisions = [e.decision for e in guard.events]
    assert decisions == [ALLOWED, DENIED]


async def test_a_redirect_to_a_public_destination_is_allowed_through_the_hop() -> None:
    _guard, context = await _guarded_context()

    first = await context.navigate(_PUBLIC)
    hop = await context.navigate("https://example.org/landed")

    assert first.action == ("continue",)
    assert hop.action == ("continue",)


# --- subresources are governed, not just documents --------------------------


@pytest.mark.ac("#855/AC-4")
@pytest.mark.parametrize("resource_type", ["xhr", "script", "stylesheet", "image", "font"])
async def test_subresources_to_a_private_destination_are_denied(resource_type: str) -> None:
    """A page cannot read internal data out through a subrequest either."""
    guard, context = await _guarded_context()

    route = await context.navigate("http://10.1.2.3/secrets.json", resource_type)

    assert route.action == ("abort", ABORT_REASON)
    assert guard.events[-1].resource_type == resource_type


@pytest.mark.ac("#855/AC-4")
async def test_public_subresources_are_allowed() -> None:
    _guard, context = await _guarded_context()

    route = await context.navigate("https://example.com/app.js", "script")

    assert route.action == ("continue",)


@pytest.mark.ac("#855/AC-4")
async def test_websocket_upgrades_are_denied_regardless_of_destination() -> None:
    """The explicitly decided WebSocket policy: refused outright.

    `context.route` does not intercept WebSocket upgrades, so leaving them
    open would be an ungoverned duplex channel — including to private
    hosts. Denial is the decided policy for both directions.
    """
    guard, context = await _guarded_context()

    private_ws = await context.open_web_socket("ws://127.0.0.1:5678/socket")
    public_ws = await context.open_web_socket("wss://example.com/live")

    assert private_ws.action is not None and private_ws.action[0] == "close"
    assert public_ws.action is not None and public_ws.action[0] == "close"
    ws_events = [e for e in guard.events if e.resource_type == "websocket"]
    assert len(ws_events) == 2
    assert all(e.decision == DENIED for e in ws_events)


# --- allowances are host-owned and stay narrow ------------------------------


@pytest.mark.ac("#855/AC-6")
async def test_a_configured_origin_is_allowed_and_the_allowance_stays_scoped() -> None:
    configure_outbound_policy("http://10.20.30.40:8443")
    _guard, context = await _guarded_context()

    allowed = await context.navigate("http://10.20.30.40:8443/wiki/page")
    other_port = await context.navigate("http://10.20.30.40:8444/wiki/page")
    other_scheme = await context.navigate("https://10.20.30.40:8443/wiki/page")
    other_host = await context.navigate("http://10.20.30.41:8443/wiki/page")

    assert allowed.action == ("continue",)
    assert other_port.action == ("abort", ABORT_REASON)
    assert other_scheme.action == ("abort", ABORT_REASON)
    assert other_host.action == ("abort", ABORT_REASON)


@pytest.mark.ac("#855/AC-6")
async def test_browser_specific_origins_layer_without_widening_the_shared_policy() -> None:
    """`BROWSER_USE_ALLOWED_ORIGINS` is a host-owned browser allowance.

    It may not widen what ordinary HTTP effects may reach — the shared
    policy must not learn the browser's origins.
    """
    _guard, context = await _guarded_context(extra_origins=["http://internal.example:9000"])

    allowed = await context.navigate("http://internal.example:9000/doc")
    same_host_other_port = await context.navigate("http://internal.example:9001/doc")

    assert allowed.action == ("continue",)
    assert same_host_other_port.action == ("abort", ABORT_REASON)
    assert not current_outbound_policy().allows("http://internal.example:9000/doc")


async def test_the_policy_is_snapshotted_at_construction() -> None:
    """A guard built before an allowance keeps the stricter view; one built
    after picks it up. Configuring later must not reach back into a live
    browser session."""
    early_guard, early_context = await _guarded_context()

    configure_outbound_policy("http://10.20.30.40:8443")
    late_guard, late_context = await _guarded_context()

    early = await early_context.navigate("http://10.20.30.40:8443/wiki/page")
    late = await late_context.navigate("http://10.20.30.40:8443/wiki/page")

    assert early.action == ("abort", ABORT_REASON)
    assert late.action == ("continue",)
    assert late_guard.policy is not early_guard.policy


def test_an_explicit_policy_needs_no_global_state() -> None:
    """A caller may hand a guard its own policy — used by the client tests
    to prove wiring without touching the process-wide allowance."""
    guard = BrowserNetworkGuard(policy=OutboundPolicy(origins=frozenset({"http://a.test:80"})))
    assert guard.policy.allows("http://a.test/x")
    assert not guard.policy.allows("http://b.test/x")


# --- the audit trail --------------------------------------------------------


@pytest.mark.ac("#855/AC-7")
async def test_events_record_origins_only_never_the_query_or_path() -> None:
    """Query strings carry search text, session ids and tokens; an audit
    trail that repeats them into logs leaks what it was guarding."""
    guard, context = await _guarded_context()

    await context.navigate("https://example.com/search?q=secret-token&page=2")
    await context.navigate("http://127.0.0.1:8080/admin?session=abc123")

    rendered = repr(guard.events)
    assert "secret-token" not in rendered
    assert "abc123" not in rendered
    assert "/search" not in rendered
    assert "/admin" not in rendered
    origins = [e.origin for e in guard.events]
    assert origins == ["https://example.com:443", "http://127.0.0.1:8080"]


@pytest.mark.ac("#855/AC-7")
async def test_denied_events_carry_a_branchable_reason_and_resource_type() -> None:
    guard, context = await _guarded_context()

    await context.navigate("http://169.254.169.254/latest/meta-data/", "document")
    await context.navigate("http://localhost/x", "xhr")
    await context.navigate("file:///etc/passwd", "document")

    reasons = [(e.reason, e.resource_type) for e in guard.denied_events()]
    assert (BLOCK_INTERNAL_ADDRESS, "document") in reasons
    assert (BLOCK_INTERNAL_HOSTNAME, "xhr") in reasons
    assert (BLOCK_SCHEME, "document") in reasons


@pytest.mark.ac("#855/AC-7")
async def test_allowed_and_denied_decisions_are_both_audited() -> None:
    guard, context = await _guarded_context()

    await context.navigate(_PUBLIC)
    await context.navigate("http://10.9.8.7/x")

    assert [e.decision for e in guard.events] == [ALLOWED, DENIED]


async def test_an_unexpected_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolver fault must not become an accidental allow: the request is
    aborted and the refusal is recorded as an error, not swallowed."""
    guard = BrowserNetworkGuard()
    context = FakePwContext()
    await guard.attach(context)

    async def _explode(url: str) -> None:
        raise RuntimeError("resolver melted")

    monkeypatch.setattr("maistro.tools.browser.guard.avalidate_outbound_url", _explode)
    route = await context.navigate(_PUBLIC)

    assert route.action == ("abort", ABORT_REASON)
    assert guard.events[-1].decision == DENIED
    assert guard.events[-1].reason == "error"


# --- attachment -------------------------------------------------------------


async def test_attach_registers_the_catch_all_route_and_web_socket_patterns() -> None:
    guard = BrowserNetworkGuard()
    context = FakePwContext()

    await guard.attach(context)

    assert [p for p, _h in context.route_handlers] == [ROUTE_PATTERN]
    assert [p for p, _h in context.ws_handlers] == [ROUTE_PATTERN]
    assert guard.websocket_governed is True
    assert context.route_handlers[0][1] == guard.handle_route


async def test_attach_without_web_socket_support_says_so() -> None:
    """No pretending a stand-in without `route_web_socket` governs them."""
    guard = BrowserNetworkGuard()
    context = FakePwContext()

    class _NoWebSocketContext(FakePwContext):
        route_web_socket = None  # type: ignore[assignment]

    bare = _NoWebSocketContext()
    await guard.attach(bare)

    assert guard.websocket_governed is False
    assert bare.route_handlers, "the request route must still be attached"
    assert context.route_handlers == []


async def test_the_handler_accepts_the_single_argument_form() -> None:
    """Playwright accepts handlers of one or two parameters; both must work."""
    from types import SimpleNamespace

    guard = BrowserNetworkGuard()
    answered: list[str] = []
    route = SimpleNamespace(
        request=SimpleNamespace(url=_PUBLIC, resource_type="document"),
    )

    async def _abort(code: str) -> None:
        answered.append(f"abort:{code}")

    async def _continue() -> None:
        answered.append("continue")

    route.abort = _abort  # type: ignore[method-assign]
    route.continue_ = _continue  # type: ignore[method-assign]

    await guard.handle_route(route)  # no request argument

    assert answered == ["continue"]

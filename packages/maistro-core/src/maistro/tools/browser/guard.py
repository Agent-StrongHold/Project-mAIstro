"""The outbound network policy, applied at the Playwright boundary (#855).

`BrowserClient.browse` validated its explicit starting URL and then handed a
real Chromium session to `browser_use.Agent`; `search_web` validated nothing at
all. The gap is not in the validator — `security/ssrf.py` is correct — but in
where it ran. A browser is not an HTTP client with one destination: it follows
redirects, loads subresources, and, under LLM control, navigates wherever the
model decides on the next step. A check on the starting URL of such a session
is a check on one of the dozens of destinations the session will touch, and
prompt text telling the model where not to go is not a control at all.

So the guard moves to the only place that sees every destination: the Playwright
route layer. `BrowserNetworkGuard.attach(context)` registers a route handler
for `**/*`, and Chromium consults that handler **before the network stack is
asked to connect** — for the first navigation, for every redirect hop, for
iframe and subresource fetches, and for the destinations an autonomous agent
invents mid-run. The decision the handler makes is the same one ordinary HTTP
effects are governed by (`ADR-082326-5386`): a configured origin passes, every
other URL is shown to `avalidate_outbound_url`, and refusing is the default.
One policy, one implementation, applied at a second seam.

What is decided for each request class
--------------------------------------
* **Main-frame navigations and redirect hops** — validated against the shared
  policy on every hop. A chain that starts public and redirects private is
  refused at the hop that matters, exactly as the httpx seam does by
  construction.
* **Subresources** (scripts, stylesheets, XHR, images, fonts, media…) — the
  same policy, not a weaker one. A page loaded from a public origin has no
  business reading `http://169.254.169.254/` or an internal host through a
  subrequest either; the data an XHR can carry out is the same data a
  navigation can. Service workers are blocked at context creation by the
  caller (`service_workers="block"`), because Playwright's route layer does
  not intercept fetches a service worker makes on a page's behalf.
* **WebSockets** — denied outright, with an audit event, whether the target is
  public or private. This is the conservative end of an explicit decision:
  `context.route` does not intercept WebSocket upgrades, and a duplex channel
  the URL-level policy cannot speak to is precisely the ungoverned path this
  module exists to close. A research/browse session does not need WebSockets;
  the day one does, the decision to allow them should be made here, in the
  open, with the destination check the upgrade actually supports — not by
  forgetting to have any.

What an allowance widens
------------------------
The base policy is the deployment's shared `OutboundPolicy` — the same
settings-seeded origins ordinary HTTP effects trust — snapshotted when the
guard is built. `BROWSER_USE_ALLOWED_ORIGINS` (comma-separated origins, set by
the operator) layers browser-specific origins on top for deployments that want
the research browser reading an internal wiki. Both are host-owned: neither
the model nor anything a page returns can widen them, and an allowance is an
exact origin — scheme, host, port — so allowing `http://10.0.0.5:8080` does
not allow port 8081, `https://`, or any other private address.

Auditable evidence, without the query string
--------------------------------------------
Every decision appends a `BrowserNetEvent` and emits a structlog event. The
event carries the **origin** — `scheme://host:port` — never the path, query or
userinfo: a URL's query is where search text, session ids and tokens travel,
and an audit trail that repeats them into logs is a leak wearing a control's
clothes. Denied decisions log at warning with the policy reason; allowed at
debug, because a real page makes hundreds of allowed subrequests and warning
would bury the signal the audit exists to carry.

Known limitation, stated rather than implied
--------------------------------------------
The rebinding window #154 described is unchanged and applies here too: the
guard resolves the name, then Chromium resolves it again to connect. Closing
that needs the resolved address pinned into the connection and is not done at
either seam.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import structlog

from maistro.security.outbound import (
    OutboundPolicy,
    current_outbound_policy,
    outbound_origin,
)
from maistro.security.ssrf import SSRFBlockedError, avalidate_outbound_url

logger = structlog.get_logger()

#: The decision vocabulary. Two values, deliberately: a request was either
#: allowed onto the network or it was not.
ALLOWED = "allowed"
DENIED = "denied"

#: The Playwright abort reason Chromium renders as `ERR_BLOCKED_BY_CLIENT` —
#: the same signal users see when an extension blocks a request, so a denied
#: navigation fails visibly rather than as a generic network error the model
#: might read as "retry elsewhere".
ABORT_REASON = "blockedbyclient"

#: The single route pattern that reaches every request the context makes:
#: main frame, iframes, subresources, and each redirect hop.
ROUTE_PATTERN = "**/*"

#: Why a WebSocket was refused. Reuses the scheme vocabulary because that is
#: the honest reason: the canonical policy allows http and https, and a
#: WebSocket upgrade is neither.
WEBSOCKET_BLOCK_REASON = "scheme"

#: Bound on the in-memory audit trail. A long browse session makes thousands
#: of requests; the events exist to answer "what did the browser try to
#: reach", and the newest thousand answer that as well as all of them would.
MAX_AUDIT_EVENTS = 1000


@dataclass(frozen=True)
class BrowserNetEvent:
    """One auditable network decision the browser transport made.

    `origin` is `scheme://host:port` with the default port made explicit —
    path, query and userinfo are dropped before construction and never
    recorded, for the reason the module docstring gives. `reason` is one of
    the `security.ssrf.BLOCK_*` constants (empty for allowed decisions);
    `resource_type` is Playwright's own taxonomy (`document`, `xhr`,
    `stylesheet`, …) so the audit can say *what kind* of request was denied,
    not just where it was going.
    """

    decision: str
    origin: str
    reason: str = ""
    resource_type: str = "unknown"


class BrowserNetworkGuard:
    """Applies the canonical outbound policy to one Playwright browser context.

    Construct, then `await guard.attach(context)` before any page exists on
    it. The handler is also callable directly with Playwright-shaped doubles,
    which is how the tests drive it without a Chromium runtime.
    """

    def __init__(
        self,
        *,
        policy: OutboundPolicy | None = None,
        extra_origins: tuple[str, ...] | list[str] = (),
    ) -> None:
        base = policy if policy is not None else current_outbound_policy()
        self._policy = base.with_origins(extra_origins)
        #: Every decision this guard has made, newest last, bounded.
        self.events: deque[BrowserNetEvent] = deque(maxlen=MAX_AUDIT_EVENTS)
        #: Whether WebSocket upgrades on the attached context are governed.
        #: `route_web_socket` has shipped with Playwright since 1.48 (the
        #: image pins >=1.49), so it is absent only on stand-ins; the guard
        #: says so rather than implying coverage it does not have.
        self.websocket_governed = False

    @property
    def policy(self) -> OutboundPolicy:
        """The policy in force for this guard, including browser allowances."""
        return self._policy

    def denied_events(self) -> tuple[BrowserNetEvent, ...]:
        """The refusals, oldest first. The slice an incident review wants."""
        return tuple(e for e in self.events if e.decision == DENIED)

    async def attach(self, context: Any) -> BrowserNetworkGuard:
        """Register this guard on a Playwright `BrowserContext` (or `Page`).

        Registration must precede the first navigation: routes apply to
        requests made after they are installed, so the caller launches the
        context, attaches, and only then hands it to browser-use.
        """
        await context.route(ROUTE_PATTERN, self.handle_route)
        route_ws = getattr(context, "route_web_socket", None)
        if route_ws is not None:
            await route_ws(ROUTE_PATTERN, self.handle_web_socket)
            self.websocket_governed = True
        else:
            logger.warning(
                "browser_net_websocket_interception_unavailable",
                detail="context lacks route_web_socket; WebSocket upgrades "
                "would not be governed by the outbound policy",
            )
        return self

    async def handle_route(self, route: Any, request: Any = None) -> None:
        """The `context.route` handler: decide, then continue or abort.

        Playwright calls handlers as `(route, request)`; the second parameter
        is optional so single-argument handler shapes and test doubles work.
        Nothing may escape this handler: an exception inside a route handler
        leaves the request hanging without a decision, so every failure path
        — policy refusal or unexpected error — aborts the request. Failing
        closed is the only direction a boundary like this may fail in.
        """
        req = request if request is not None else getattr(route, "request", None)
        url = str(getattr(req, "url", "") or "")
        resource_type = str(getattr(req, "resource_type", "") or "unknown")
        try:
            await self._decide(url)
        except SSRFBlockedError as exc:
            await _abort(route)
            self._record(DENIED, url, exc.reason or "policy", resource_type)
            return
        except Exception:
            # A resolver fault, a malformed URL, anything unexpected: the
            # request cannot be shown to be allowed, so it is not.
            await _abort(route)
            self._record(DENIED, url, "error", resource_type)
            return
        await _continue(route)
        self._record(ALLOWED, url, "", resource_type)

    async def handle_web_socket(self, ws_route: Any) -> None:
        """The `route_web_socket` handler: WebSocket upgrades are refused.

        See the module docstring for why outright refusal is the decided
        policy rather than a destination check on the upgrade URL.
        """
        url = str(getattr(ws_route, "url", "") or "")
        await _close_web_socket(ws_route)
        self._record(DENIED, url, WEBSOCKET_BLOCK_REASON, "websocket")

    async def _decide(self, url: str) -> None:
        """The canonical decision: a configured origin passes, the rest prove
        themselves public. This is `enforce_outbound_policy`'s rule against
        this guard's snapshotted policy (which may carry browser allowances
        the shared one does not)."""
        if self._policy.allows(url):
            return
        await avalidate_outbound_url(url)

    def _record(self, decision: str, url: str, reason: str, resource_type: str) -> None:
        # The origin, never the URL: `outbound_origin` drops path, query and
        # userinfo, so the audit cannot repeat whatever the query carried.
        origin = outbound_origin(url)
        event = BrowserNetEvent(
            decision=decision, origin=origin, reason=reason, resource_type=resource_type
        )
        self.events.append(event)
        if decision == DENIED:
            logger.warning(
                "browser_net_denied",
                origin=origin,
                reason=reason,
                resource_type=resource_type,
            )
        else:
            logger.debug("browser_net_allowed", origin=origin, resource_type=resource_type)


async def _abort(route: Any) -> None:
    """Best-effort abort. The route may already be handled (a racing handler,
    a closed page); the decision is recorded either way, and an abort that
    cannot be delivered must not turn a policy refusal into a traceback."""
    try:
        await route.abort(ABORT_REASON)
    except Exception:
        logger.debug("browser_net_abort_undeliverable")


async def _continue(route: Any) -> None:
    try:
        await route.continue_()
    except Exception:
        # A continue that races a navigation away is not a policy event; the
        # request itself is what the guard decided about.
        logger.debug("browser_net_continue_undeliverable")


async def _close_web_socket(ws_route: Any) -> None:
    try:
        await ws_route.close()
    except Exception:
        logger.debug("browser_net_websocket_close_undeliverable")


__all__ = [
    "ABORT_REASON",
    "ALLOWED",
    "DENIED",
    "MAX_AUDIT_EVENTS",
    "ROUTE_PATTERN",
    "WEBSOCKET_BLOCK_REASON",
    "BrowserNetEvent",
    "BrowserNetworkGuard",
]

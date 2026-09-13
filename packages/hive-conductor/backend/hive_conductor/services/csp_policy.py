"""What the Conductor's front end actually loads, expressed as a policy (#310).

`maistro.security.content_security_policy` knows the shape a policy must have.
This knows the facts only this application can know: which origins its own SPA
fetches from, and which of them are there on purpose.

Every source below is present because something in `frontend/` needs it, and
the list was derived by reading that tree rather than by copying a template. A
directive nobody can trace to a real fetch is a permission granted to an
attacker for free.

## No third-party origins

There are none. `frontend/index.html` used to load Inter, JetBrains Mono and
Caveat from Google Fonts, which is why `style-src` admitted
`fonts.googleapis.com` and `font-src` admitted `fonts.gstatic.com`. #377
self-hosted the two families anything actually referenced — Vite emits their
woff2 files as same-origin assets — and dropped Caveat, which nothing used.
Every directive below is now `'self'` or `'none'`, and the only widening any
deployment can produce is the two development origins named further down.

The test that anchors this reads `index.html` and asserts the set of external
origins there and the set in the policy are both empty. That is what keeps the
policy honest when someone adds a CDN: the failure arrives in CI rather than in
a header nobody reads.

## Why no `'unsafe-inline'` in `style-src`

Four places used to inject a `<style>` element at runtime, each holding
constant CSS — three keyframes and one page's stylesheet. Every one of them is
now in a served stylesheet, so the policy does not have to admit inline styles
to keep the application working, and an injected `<style>` gains nothing.

React's `style={{…}}` prop is unaffected either way: it assigns through the
CSSOM rather than writing a `style` attribute, and CSP governs the attribute.
"""

from __future__ import annotations

from maistro.security.content_security_policy import NONE, SELF, ContentSecurityPolicy

#: Vite's dev server, which the SPA's HMR client opens a WebSocket back to.
#: Only ever added to a development policy.
VITE_DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "ws://localhost:5173",
    "http://127.0.0.1:5173",
    "ws://127.0.0.1:5173",
)


def conductor_policy(*, development: bool = False) -> ContentSecurityPolicy:
    """The policy served with every response.

    `development` widens exactly two things and is driven by the same
    `ALLOW_INSECURE_TRANSPORT` flag #369 introduced — the one place a
    deployment declares itself a local run, and one that start-up already
    refuses to combine with a production cookie posture. A second, independent
    "dev mode" switch would be a second way to ship the loose policy by
    accident.
    """
    connect: tuple[str, ...] = (SELF, *VITE_DEV_ORIGINS) if development else (SELF,)

    directives: dict[str, tuple[str, ...]] = {
        # The floor. Everything not named below falls back to this, including
        # directives the spec has not added yet.
        "default-src": (SELF,),
        # No inline, no eval, no CDN. Vite emits the bundle as a served module.
        "script-src": (SELF,),
        # Both were third-party before #377 self-hosted the typefaces. The
        # stylesheet Vite emits and the woff2 files it references are served
        # from this origin, so neither directive needs anything else.
        "style-src": (SELF,),
        "font-src": (SELF,),
        # `data:` for avatars and generated thumbnails the API returns inline;
        # `blob:` for images the browser builds itself, which the canvas and
        # deck surfaces do.
        "img-src": (SELF, "data:", "blob:"),
        # The API, the SSE stream and the WebSocket are all same-origin.
        "connect-src": connect,
        # Nothing is embedded and nothing embeds us. `frame-ancestors`
        # supersedes X-Frame-Options in any browser that reads it; the older
        # header stays for the ones that do not.
        "frame-src": (NONE,),
        "frame-ancestors": (NONE,),
        # `<object>` and `<embed>` execute plugin content and nothing here uses
        # them.
        "object-src": (NONE,),
        # An injected `<base href>` silently repoints every relative URL on the
        # page, including the script tags the policy just constrained.
        "base-uri": (SELF,),
        # An injected form action is how a page that cannot run script still
        # exfiltrates what the user types into it.
        "form-action": (SELF,),
    }

    if not development:
        # Refuses a plain-HTTP subresource on a page served over HTTPS. Omitted
        # in development because a local run *is* plain HTTP, and the directive
        # would upgrade every request to a port nothing is listening on. It
        # carries no sources: the directive is its own instruction.
        directives["upgrade-insecure-requests"] = ()

    return ContentSecurityPolicy.build(directives)

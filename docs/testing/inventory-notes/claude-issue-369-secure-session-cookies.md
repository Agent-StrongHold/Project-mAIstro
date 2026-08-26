---
inventory-delta:
  packages/maistro-core/tests: +32
  packages/maistro-server/tests: +2
  packages/hive-conductor/backend/tests: +16
---
# claude-issue-369-secure-session-cookies

Fifty new node IDs across three suites. Thirty-two in a new
`packages/maistro-core/tests/security/test_transport.py`, sixteen in the
Conductor (thirteen in a new `test_session_cookie_policy.py`, three added to
`test_security_headers.py`), two in `maistro-server`. Nothing removed.

**One test was inverted rather than added**, in each of the two apps — see
"A test that asserted the defect" below. Those are counted in the numbers above
as replacements, not additions.

## The default was the problem, and the reason for it was sound

`session_cookie_secure` defaulted to `False`, with this comment:

> Off by default because the documented dev loop is http://localhost:8101 and a
> Secure cookie is silently dropped there, which would look like "login does
> nothing".

Every word of that is true. A `Secure` cookie really is dropped over `http://`,
and the failure really does present as login silently not working. It is a good
argument for a **local-development escape**. It is not an argument for the
default.

A default is the shape every deployment that did not think about it takes. So
the sentence the old default actually asserted was "every deployment that did
not think about this sends its session cookie in the clear", which is the wrong
way round — and the issue's own framing: *"this makes the insecure setting the
realistic deployment shape rather than a development-only exception"*.

## Two settings, not one value

`ALLOW_INSECURE_TRANSPORT` is deliberately separate from
`SESSION_COOKIE_SECURE` rather than being a third value of it. Turning off a
security control and declaring a development run are different statements, and
collapsing them into one setting is how the first becomes invisible inside the
second. Separate, the escape is a sentence someone wrote on purpose and a
reviewer can grep for.

`test_the_development_escape_has_to_be_stated_separately` and
`test_the_escape_alone_does_not_weaken_a_secure_deployment` pin both halves:
the escape is required *in addition*, and setting it on a TLS deployment does
not make the cookie insecure — it only waives the refusal.

## The startup check raises, and is not inside the try

`lifespan` wraps every other start-up step in `try/except` and logs a warning,
because a Conductor without a design service is still a Conductor. This check
sits above all of them and outside any handler: a Conductor that will send its
session cookie over plaintext is not a degraded Conductor, it is one whose
sessions any network in the path can lift.

A warning would not do. A warning about a cookie is read once, by whoever ran
the container, in a log nobody keeps.
`test_lifespan_calls_the_check_outside_a_try` reads the source for that
property, because it is about *where the call sits* rather than what it
returns.

## The forwarded header nobody was checking

Both `SecurityHeadersMiddleware` copies carried this:

    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",")[0].strip().lower() == "https"

The first half is fact — the ASGI server knows what it accepted. The second is
a **claim by the client**, believed from anyone. Any caller could send
`X-Forwarded-Proto: https` to a plain-HTTP deployment and be answered with HSTS
for two years including subdomains.

A header a browser will not send is not much of an attack by itself. A header
that decides a security control, accepted from whoever sends it, is a control
that is not enforced — and that is the AC's *"forwarded headers are accepted
only from trusted proxies"*.

The decision moved into `maistro.security.transport` rather than being fixed
twice. Both copies were wrong in the same way, which is what a duplicated
security decision does: it gets fixed in one place and stays broken in the
other. The *header-setting* stayed duplicated — two short lists of static
headers drifting apart costs nothing.

### The immediate peer, not the chain

`X-Forwarded-For` can be appended to by anyone upstream, so walking it to find
"the real client" means trusting the very thing under test. The socket peer is
the one address in a request a caller cannot choose. A deployment running
proxies in series has to list every hop that appends, which is the honest cost
of that arrangement rather than a limitation of the check.

### Nothing named means nothing trusted

`TRUSTED_PROXY_IPS` defaults to empty. A deployment that forgets to name its
proxy loses HSTS rather than gaining a header anyone can forge — the safe
direction to get wrong. `test_naming_no_proxy_trusts_nobody` states it.

## A test that asserted the defect

`test_hsts_present_when_forwarded_proto_is_https` existed in **both** apps and
asserted that a forwarded header from any caller earns HSTS. It was not a bad
test of a good behaviour; it was an accurate test of the wrong behaviour, which
is the kind that keeps a defect alive through every future refactor.

Both are inverted, and the legitimate arrangement the header exists for — TLS
terminated at a proxy the deployment named — is now covered in both directions,
including a trusted proxy reporting plain `http`. Trust runs both ways.

## Why two conftests declare themselves local-development

Flipping the default broke **462 of 1 355 Conductor tests** and 17 of 26 Turing
tests. Not a subtlety: those suites drive their apps over plain HTTP through
`TestClient`, which never sends a `Secure` cookie back, so every route test
needing a session failed with no session.

The suites now set the same two settings a developer running the service
locally sets, in `conftest.py`, with the reasoning written down. The
alternative — weakening the production default so the tests pass — is precisely
the arrangement this issue exists to undo.

That does mean these suites no longer exercise the production cookie shape, so
`test_session_cookie_policy.py` asserts it directly, building `Settings` with
`_env_file=None` and the relevant variables deleted. Reading the real default
required stepping around *both* the conftest environment and any `.env` on the
machine; a test about a default that a stray `.env` can flip is not a test
about the default.

## maistro-turing's cookie had none of it

No `secure`, no `max_age`, no `path`. The missing `max_age` is the one worth
naming: a cookie without it lives as long as the browser *process*, which on a
machine that is never rebooted and a browser that restores tabs is
indefinitely. The AC asks for a bounded lifetime and "until you quit Chrome" is
not one.

## Discrimination, measured

Against `develop`: the whole core suite fails to import (the module is new),
and both apps' HSTS tests fail — `test_hsts_absent_when_an_untrusted_caller_
claims_https` in each is the inverted one, and it fails because `develop`
sends the header.

`test_the_session_cookie_is_secure_by_default` asserts the exact opposite of
what `develop` produces.

## Not covered here

- **Browser E2E verifying effective cookie attributes.** The DoD asks for it.
  What is here proves the attributes the server *sets*; proving what a browser
  *stores* needs the Playwright lane, which is a different job from this one.
- **CSRF and session fixation.** Named in the AC. Session rotation on login and
  revocation on logout already exist and are tested; CSRF is a token scheme
  this change neither adds nor removes, and adding one alongside a cookie-policy
  change would make both harder to review.
- **A tracked overlay that uses plain HTTP.** The issue names one. The startup
  refusal makes such an overlay fail loudly rather than silently, which is the
  behaviour change that matters; auditing every overlay for its transport is a
  follow-up with its own evidence.

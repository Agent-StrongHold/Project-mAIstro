---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# claude-issue-368-mcp-health-ssrf

Nine new node IDs in `packages/hive-conductor/backend/tests/test_mcp_routes.py`:
seven in `TestAPolicyRefusalIsNotADownServer`, two in `TestTheFanOutIsBounded`.
Nothing removed or reparametrised.

## The premise was already half-fixed, and the report says so

#368 states that MCP health checks "fetch stored server URLs without the shared
outbound SSRF guard". Measured against `develop`, that is **no longer true** —
#155 put the outbound policy in front of every transport at the `shared_client`
seam, and `_health_check` goes through it. Probed directly:

| Target | Result |
|---|---|
| `http://127.0.0.1:9/` | blocked |
| `http://169.254.169.254/latest/meta-data/` | blocked |
| `http://10.0.0.1/` | blocked |
| `http://[::1]:9/` | blocked |
| `http://user:pw@127.0.0.1:9/` | blocked |
| `file:///etc/passwd` | blocked (scheme) |

Redirects are not followed (`shared_client` defaults `follow_redirects=False`
and the health path does not override it), so there is no hop to revalidate.
Stored MCP URLs are never seeded into `configure_outbound_policy`, so an
internal origin stays refused unless an operator configures it — which is what
the "narrow explicit authorization seeded from canonical settings" criterion
asks for.

What was left is the DoD's last line: **"Outbound decision and target provenance
are auditable."**

## A refusal and a down server are not the same event

`_health_check` caught `except Exception`, logged an `error_swallowed` warning
with a **hardcoded line number that had already drifted**, and returned
`disconnected`. So these two produced an identical report:

- the origin is refused by outbound policy, and will be on every future check
  until someone configures it or changes the URL;
- the server is simply not running.

They need opposite responses from an operator, and the second reads as
transient. A refusal is now `status="error"` with a `last_error` naming the
reason; the frontend already renders the raw status string, so no UI change is
needed for the distinction to show.

## Why "any block is an error" would have been a new inaccuracy

The obvious version of this fix is wrong, and the existing test caught it. The
guard **fails closed on a host it cannot resolve**:

    Outbound URL blocked (host 'example.invalid' could not be resolved,
    so it cannot be shown to be external)

That is a DNS outcome, not an authorization decision — the same situation as a
server being down. Mapping every `OutboundBlockedError` to `error` would have
replaced one inaccuracy with its mirror image, and
`test_list_servers_marks_non_atlassian_unreachable_as_disconnected` went red
immediately, which is how it was caught.

Message strings cannot be branched on safely, so `SSRFBlockedError` gained a
`reason` carrying one of six `BLOCK_*` constants, and `OPERATIONAL_BLOCKS` names
the two that mean "not reachable" rather than "refused". The reason propagates
through `OutboundBlockedError`, whose dual-contract inheritance is unchanged.
`test_an_unresolvable_host_stays_disconnected` is the case that pins the
distinction in the direction that is easy to get wrong.

## `test_the_refusal_names_the_origin_not_the_url`

`last_error` reaches the browser and the log line reaches disk, and a stored MCP
URL can carry a token in its query string or userinfo. Both carry
`outbound_origin(url)` — scheme, host, port — never the URL. The test registers
`http://user:pw@127.0.0.1:9/?token=secret123` and asserts neither the token nor
the credentials appear.

`test_a_healthy_server_carries_no_error` covers the clearing direction: without
it a server refused once keeps explaining itself after its URL is corrected.

## `TestTheFanOutIsBounded`

`GET /v1/mcp/servers` ran `asyncio.gather` over the entire store, so one request
issued one outbound connection per registered server simultaneously — a caller
who can add servers could amplify a single GET arbitrarily. A semaphore caps it
at `HEALTH_FANOUT_LIMIT`.

The test counts *live* concurrent checks rather than asserting the semaphore
exists, so replacing the bound with something that does not actually bound fails
it. `test_every_server_is_still_checked` is the counterweight — bounding must
not drop anyone from the result — and is the one case here that is a regression
guard rather than a discriminator.

## Discrimination, measured

With `routes/mcp.py`, `models/schemas.py`, `security/ssrf.py` and
`security/outbound.py` reverted and the tests left in place: **8 of 9 fail**.
The ninth is `test_every_server_is_still_checked`, which is neutral by design.

`formal/` — 417 property-based conformance cases, which cover the SSRF
invariants — passes with the `reason` field added.

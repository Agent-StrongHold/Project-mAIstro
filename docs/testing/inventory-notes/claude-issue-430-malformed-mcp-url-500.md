---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
  packages/maistro-core/tests: +8
---
# claude-issue-430-malformed-mcp-url-500

Fourteen new node IDs across two suites. Six in
`packages/hive-conductor/backend/tests/test_mcp_routes.py`
(`TestOneBadRecordCannotBreakTheListing`), and eight in
`packages/maistro-core/tests/security/` — five in
`test_outbound_policy.py::TestOutboundOriginIsTotal` and three in
`test_ssrf.py::TestAsyncFormAgrees`. Nothing removed or reparametrised.

## Why the core half is in the core suite

The first version put `TestOutboundOriginIsTotal` beside the route that
surfaced the defect, in the Conductor's suite. The diff-coverage gate then
failed on `outbound.py` (50% of 4 changed lines) and `ssrf.py` (50% of 2) —
because the run that measures `maistro-core` does not execute the Conductor's
tests, so the two guards this change added had **no** covering test in the
suite that governs them.

That is not a coverage technicality. `outbound_origin` returning a sentinel
that matches no configured allowance is a core security property, and the
`UnicodeError` the resolver raises is core behaviour; a test for either that
only runs in a downstream package's suite is a test the owning package does
not have. The class moved rather than being duplicated, and the async
resolver case is now pinned in `test_ssrf.py` beside the sync one it had
diverged from.

Measured after the move: `ssrf.py` 100%, `outbound.py` 99% — the one
remaining line is `GuardedTransport.aclose`, which this change did not
touch.

## A regression I introduced, found after it merged

#428 narrowed `_health_check`'s `except Exception` so a policy refusal could be
told from a down server. That was right, and it removed a real defect. It also
removed a blanket that had been covering two exceptions the guard never
translated — Codex found both, on the merged commit.

`POST /v1/mcp/servers` takes `url` as an unrestricted string and `list_servers`
gathers over every stored record, so either one made **the whole listing** 500,
not just its own row.

## 1. Describing a refusal must not be the thing that fails

    >>> outbound_origin("http://[::1")
    ValueError: Invalid IPv6 URL

`_check_shape` reaches the right conclusion about that URL safely and raises
`SSRFBlockedError`. The refusal branch then formatted its message with
`outbound_origin(server.url)` — re-parsing the same URL, unguarded, from inside
the handler that had already refused it.

`outbound_origin` is now total. It returns `"unparseable://:invalid"`, a
sentinel rather than an empty string for the same reason the port branch
directly below it already returned one: this value is compared against
configured allowances, and **an origin nobody can parse must never compare equal
to one an operator authorized**. `://` cannot appear in a real origin, so
nothing configurable matches it.

`test_the_sentinel_matches_no_configured_allowance` is the case that pins that
security property, rather than only pinning that no exception escapes.

## 2. `UnicodeError` is a resolution failure

An ASCII label longer than 63 characters parses fine as a URL and is invalid for
DNS:

    >>> socket.getaddrinfo("a" * 64 + ".example.com", 80)
    UnicodeError: label empty or too long

`getaddrinfo` raises it *before* any lookup. The guard translated
`socket.gaierror` and not this, so it escaped the guard, escaped
`except httpx.HTTPError`, and escaped `asyncio.gather`.

It now joins `gaierror` under `BLOCK_UNRESOLVABLE`, which is the honest
classification: the host is not there.
`test_an_over_long_label_reads_as_unreachable` asserts it lands on
`disconnected` rather than `error` — an unresolvable host is a down server, and
#368's distinction has to survive this fix rather than be blurred by it.

## 3. A net that does not recreate the defect

The two escapes are fixed at their source; `except Exception` returns as the net
under the next one. It is deliberately **not** what #368 removed:

| | pre-#368 | here |
|---|---|---|
| status | `disconnected` | `error` |
| log | `warning`, no traceback | `logger.exception` |
| reads as | "start the server" | "this could not be checked" |

`test_an_unexpected_failure_is_loud_and_not_reported_as_down` pins all three. A
fallback that quietly reported `disconnected` would put back the exact defect
#368 existed to remove, and would be worse than no net at all.

## Discrimination, measured

All ten fail against `develop` at `b3ee037` — the merged state — and pass with
the fix. `test_a_good_server_still_lists_beside_a_bad_one` is the one that
states the consequence rather than the mechanism: one unusable record used to
take every other server's row with it.

`formal/` — 417 property-based conformance cases, covering the SSRF invariants
— passes with both `ssrf.py` changes.

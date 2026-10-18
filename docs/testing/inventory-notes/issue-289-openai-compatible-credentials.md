---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/hive-conductor/tests/e2e: +0
---

# Issue #289: OpenAI-compatible credential lifecycle

Adds backend API tests covering the generic OpenAI-compatible provider catalog,
credential-write authorization, non-persisting connectivity/model discovery
probe, encrypted-key create and rotation, metadata-only edit, disable, delete,
and config-only cleanup lifecycle. The probe uses a transport seam, so the test
never needs a live gateway or credential.

`test_openai_compatible_probe_over_real_transport` complements the stubbed
probe tests with the real guarded transport: a loopback HTTP server reachable
only because saving the config registered that exact origin with the outbound
policy (#67) proves live model discovery, the `connectivity` category for a
refused connection, and that a redirect hop to a never-registered private
address is refused as `policy rejection`.

`openai-compatible-credentials.spec.ts` drives the page in a browser against a
live hive-conductor (compose `e2e-tests` tier): create from config alone, the
test button's failure surface for a refused endpoint, key rotation, an edit
asserted at the wire to carry no secret, disable/enable, and delete leaving no
config behind. Successful discovery is deliberately not claimed in the browser
(the compose stack ships no live OpenAI-compatible endpoint); it is proven
server-side through the real transport by the backend test named above.

Inventory correction: the e2e delta was originally claimed as `+1`, but the
suite inventory counts pytest node IDs and the e2e recipe collects only the
directory's Python tests — a Playwright `.spec.ts` journey never becomes a
collected node, so the claim could never be collected and the gate read it as
−1 drift (same correction as the #768/#817/#380 notes). The browser corpus is
real evidence but is not part of the counted ledger.

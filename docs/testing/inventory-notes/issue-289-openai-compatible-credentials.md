---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
  packages/hive-conductor/tests/e2e: +0
  packages/maistro-core/tests: +1
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

`test_authorization_header_injects_optional_gateway_identity` closes the
maistro-core half of the same feature: the optional `organization`/`project`
identity headers on `GatewayEndpoint.authorization_header()` (issue #289).
It asserts all three arc combinations — plain gateway (neither header), full
identity (both headers, no bearer without an api key), and partial
(organization without project) — so the changed lines and both branch arcs
are covered where the coverage producers actually measure this module (the
core suite, not hive-conductor's backend suite, which never feeds maistro-core
coverage).

The four additional backend tests pin the probe's degenerate paths the
collection of changed lines in `routes/credentials.py` deserves:
`test_openai_compatible_config_validation_rejects_invalid_endpoint_values`
walks every 422 branch of `_validate_openai_config` (required/oversized
display name, required/oversized base URL, unparsable port, oversized
identity fields on the merged config) and proves a rejected save persists
nothing; `test_openai_compatible_test_route_rejects_bad_requests` covers the
probe route's 404/400/422/503 answers (unknown provider, unknown config
field, blank draft key, no stored key, vault unavailable);
`test_openai_compatible_probe_transport_classifications` pins the transport
classification table (timeout and socket death → `connectivity`, HTTP 404
and non-JSON `/models` → `incompatible API behavior`); and
`test_delete_draft_credential_without_secret_or_config_404s` pins the
delete-a-draft 404. Two of these branches are reachable only through the
probe route because the generic per-value cap on PUT config answers 400
before endpoint-specific validation runs — the tests assert that exact
division rather than inventing a PUT path that cannot exist.

Inventory correction: the e2e delta was originally claimed as `+1`, but the
suite inventory counts pytest node IDs and the e2e recipe collects only the
directory's Python tests — a Playwright `.spec.ts` journey never becomes a
collected node, so the claim could never be collected and the gate read it as
−1 drift (same correction as the #768/#817/#380 notes). The browser corpus is
real evidence but is not part of the counted ledger.

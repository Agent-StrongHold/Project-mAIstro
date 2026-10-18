---
inventory-delta:
  packages/maistro-server/tests: +3
---
# 953 — Extension lifecycle reads are authenticated (#953 repair round)

The three GET handlers on `/v1/extensions` (`get_extension_installation`,
`get_extension_installation_transitions`, `get_active_extension`) declared no
`RequireAuth` dependency, so with `API_KEYS` configured an unauthenticated
caller read `granted_permissions`, `authorized_by` and the full transition
audit trail for any guessable `org_id` + `extension_id`, while every POST on
the same router answered 401. A live probe against the unfixed tree returned
200 on all three reads without a token and 401 on the `expired-authorizations`
POST control; the router's own contract line in `main.py` ("Every route is
authenticated") was false for reads. The fix adds `auth: RequireAuth` to the
three handlers — the same shape every other router uses for reads.

## packages/maistro-server/tests (+3)

`api/test_extensions_api.py::TestReadsAreAuthenticated` drives the real
router with real auth (API_KEYS configured through the `get_settings`
dependency; no `verify_api_key` override) over one record driven to ACTIVE:

- `test_reads_reject_missing_token` — all three reads answer 401 without any
  credential, and the body leaks neither `granted_permissions` nor
  `authorized_by`.
- `test_reads_reject_invalid_token` — a wrong bearer secret answers 401.
- `test_reads_accept_valid_token` — the guard does not lock out legitimate
  operators: the valid key reads all three views, and the record view still
  displays the snapshot permissions.

Fail-before record: against the unfixed tree at `33f7f084f1f2` the first two
tests failed with `('installation', 200, ...)` / 200-instead-of-401 on every
read while `test_reads_accept_valid_token` passed — the tests catch the
regression, not the fixture.

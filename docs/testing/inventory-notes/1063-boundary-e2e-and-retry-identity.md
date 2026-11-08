---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# 1063-boundary-e2e-and-retry-identity

Closes the two acceptance items reopened issue #1063 still tracked after
PRs #1346/#1375: the boundary-level E2E and the retry/replay identity
property. Tests only — no production code changed; the correlation seam
those PRs built is the code under test.

- `packages/hive-conductor/backend/tests`: +4 — new suite
  `test_request_correlation_boundary.py` drives the real Hive `main:app`
  (RequestIDMiddleware → auth → missions route → EngineService →
  `MaistroServerTaskBackend`) against the real maistro-server ASGI app
  (RequestIDMiddleware → auth → /tasks → TaskQueue → `TaskRunAdmitter` →
  SQLite Run spine + idempotency claims), with httpx's `ASGITransport` as the
  only substitution, at the HTTP client edge:
  - `test_one_request_id_crosses_the_boundary_onto_the_run` — one
    client-supplied id appears in Hive's response echo, on the forwarded
    service-hop request, and in the admitted Run's provenance (regression
    coverage for a dropped header and an admitter that stops recording).
  - `test_a_retried_request_keeps_the_same_logical_identity` — a dropped
    connection on the first transport attempt (Hive answers its own 500 with
    the id attached) followed by the caller's retry re-sending the same
    logical request: both forwarded attempts carry the same id and the Run
    the retry admitted records it.
  - `test_a_transport_replay_reconciles_to_one_run_with_one_identity` — a
    byte-identical replay of one submission reconciles through the #1176
    claim store to the same Run, which carries the one request id.
  - `test_background_admission_gets_a_new_correlation_root` — a submission
    with no request in scope forwards no id and the server mints a fresh
    12-hex root onto the Run, never an earlier request's id.

Negative verification: dropping the `X-Request-ID` forward in
`MaistroServerTaskBackend._headers` fails 3 of the 4; removing the
`request_id` provenance write in `_admission_provenance` fails all 4.

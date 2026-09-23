---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/maistro-server/tests: +2
---
# fix-m1-1063-request-correlation-remainder-86a8

Two of #1063's open acceptance items, closed with new tests (no production
code changed):

- `packages/maistro-core/tests`: +1 — `test_a_task_admitted_through_the_http_boundary_carries_one_id_into_execution`
  ties together the two already-tested halves of the NodeRun/Attempt/Event
  chain (admission's provenance write, direct-execution propagation) into
  one end-to-end assertion: a task admitted inside the exact
  `bind_execution_context` binding `RequestIDMiddleware` establishes for an
  HTTP-borne request carries the same request id onto both the Run's
  provenance and the executor's ambient context/log lines.
- `packages/maistro-server/tests`: +2 — `test_request_id_cannot_assert_workspace_scope`
  and `test_request_id_cannot_impersonate_the_workspace_scope_signature` pin
  the negative: `X-Request-ID` is correlation metadata only. A caller cannot
  use it to select a Workspace it has no signed proof of membership for, even
  when the header is set to a real Workspace id or to the exact HMAC that
  would authorize one — admission still falls through to the configured
  default Workspace, and the id itself still round-trips onto the Run's
  provenance untouched.

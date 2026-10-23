---
inventory-delta:
  packages/maistro-server/tests: +1
---

# #860 F9 — POST /tasks answers a full active-Run ceiling with 429, not 500

(+1 node in gated suite `packages/maistro-server/tests`:
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py::
test_full_ceiling_answers_429_with_retry_after`.)

## What the soak found

The #860 soak's sustained admission share fills the per-principal
active-root-Run ceiling (baseline 8, #1182) within seconds of the window. The
refusal shape — `RunConcurrencyExceeded`, documented as retryable backpressure
("the same request is admissible once a slot frees") — escaped
`maistro_server/api/tasks.py::create_task` unhandled and surfaced as an
unhandled 500 + full ASGI traceback per refused submission. Observed live in
the round-5 F3 bisect: 100 of 131 concurrent submissions through the LB got
`500` with `RunConcurrencyExceeded: active root Run ceiling reached for
principal: 8 active, limit 8`.

A designed rejection reading as a server fault breaks the H6 admission
contract twice: it inflates the error class the soak gate treats as
unavailability, and it gives the client nothing actionable (no `Retry-After`).
Before this fix, the storm-masked soak evidence could not have distinguished
"admission unavailable" from "admission backpressured".

## The fix

`create_task` maps `RunConcurrencyExceeded` to `429 Too Many Requests` with a
`Retry-After` header — the same translation layer that already maps
`InvalidIdempotencyKey` → 422 and `IdempotencyKeyMismatch` → 409. The header
is set on the `HTTPException` itself (`headers=`): setting it on the injected
`Response` parameter is dropped when the exception handler builds the error
response (regression-tested). The ceiling, its baselines, and every other
admission transport are untouched — this is the HTTP translation seam only.
Other admission transports (chat, A2A, scheduler) are separate handlers and
were not falsified by the soak; if one of them grows an equivalent 500 shape
under load, that is a separate finding.

## The test

`test_full_ceiling_answers_429_with_retry_after` wires the exact production
surface (router through the process queue singleton onto a real Run spine via
`wire_execution_spine(None, ...)`, settings overridden so two bearer tokens
resolve to two principals — the same pattern as the idempotency contract
tests). With no runner started, admitted Runs stay QUEUED and keep holding
their active slots, so the tightened `per_principal=2` ceiling fills
deterministically. Assertions: 202 within the ceiling, 429 + `Retry-After`
over it with the ceiling named in the detail, a second principal unaffected by
the first's full slots, and readmission after a slot frees (backpressure is
not a latched refusal).

Verified: `uv run pytest packages/maistro-server/tests/api/ -q` → 407 passed
(includes the new node); suite inventory drift is exactly this +1.

---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +9
---
# fix-m1-1063-conductor-request-correlation

Eleven new tests for #1063: one canonical request correlation identity across
the Hive Conductor -> maistro-server task-admission boundary. All new;
nothing removed or renamed.

**The gap.** Hive Conductor had no `RequestIDMiddleware` and never handled
`X-Request-ID`; `MaistroServerTaskBackend.submit(...)` forwarded the signed
Workspace-scope headers but no correlation identity; maistro-server's own
`RequestIDMiddleware` therefore always allocated a fresh id for the
service-to-service hop; and `TaskRunAdmitter.admit()` recorded `task_id`,
`session_id`, and `user_id` in Run provenance but never `request_id`. A
background-fired schedule had no correlation root at all.

**The fix reuses one existing vocabulary rather than inventing a second.**
maistro-core's `RequestIDMiddleware` (already used by maistro-server) is now
also registered in Hive Conductor's own middleware stack, wrapping
Auth/Privilege/RequestLog/CORS and the route handler so the id is bound onto
the canonical `ExecutionContext` before any of them run. `_headers()` on
`MaistroServerTaskBackend` forwards that bound id under the same
`X-Request-ID` header maistro-server's middleware already reads — unsigned,
unlike the Workspace-scope headers, since a request id is correlation
metadata only and must never assert scope. `TaskRunAdmitter.admit()` reads
`current_execution_context().request_id` and records it in provenance the
same way it already does for `session_id`/`user_id`, omitted rather than
blank when nothing is bound. A schedule firing (`_ScheduleRunner._fire_schedule`)
has no incoming request, so it now runs inside `detached_execution_context()`
(the same primitive documented for a transactional-outbox publisher) and
mints its own fresh id, so it can neither go uncorrelated nor inherit a
stray Attempt's ids left bound on a shared event loop tick.

**`packages/maistro-core/tests/tasks/test_admission.py` (+2).** A bound
`request_id` lands in the admitted Run's provenance; with nothing bound, the
key is absent rather than an empty string, matching the existing
session/user discipline in the same file.

**`packages/hive-conductor/backend/tests/test_request_id_middleware.py`
(+5, new file).** Drives the real `main:app` stack via `TestClient`, following
`test_security_headers.py`'s convention: a fresh id appears with none sent
and differs between two requests; a valid client-supplied id is echoed back;
an invalid one (no letter/digit) is replaced; and the id is present even on
an early 401 from `AuthMiddleware`, proving `RequestIDMiddleware` wraps it
rather than sitting inside it.

**`packages/hive-conductor/backend/tests/test_workspace_scoped_submission.py`
(+2).** `MaistroServerTaskBackend` forwards the bound id as an outbound
`X-Request-ID` header; with nothing bound, the header is omitted rather than
a fabricated value maistro-server would treat as a real client id.

**`packages/hive-conductor/backend/tests/test_scheduler.py` (+2).** A
schedule firing mints its own `request_id` and does not leak a stray ambient
one bound before the fire (simulating a shared event loop); two firings of
the same schedule get two different ids.

**Not attempted here.** #1063's e2e acceptance bullet (a real Hive ->
maistro-server HTTP round trip proving the same id lands in both services'
logs and the resulting Run) is covered at the unit/component level above,
not with a live two-process integration test — none exists yet for this
boundary to extend, and standing one up is a larger, separable piece of
work. Invalid/duplicate/oversized client `X-Request-ID` normalization is
exercised at the middleware level (reused, not reimplemented) rather than
re-tested per call site.

Full `packages/maistro-core/tests/tasks/`, `packages/hive-conductor/backend/tests/`,
and `packages/maistro-server/tests/` pass. `ruff check`/`ruff format --check`
clean on every touched file. `mypy --strict packages/maistro-core/src`
clean (hive-conductor's flat-layout app is not in the CI mypy loop).

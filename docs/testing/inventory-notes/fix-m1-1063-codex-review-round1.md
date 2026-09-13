---
inventory-delta:
  packages/maistro-core/tests: +3
  packages/hive-conductor/backend/tests: +5
---
# fix-m1-1063-codex-review-round1

Ten more tests fixing 5 findings from the Codex review on `30269f8` (the
initial #1063 push). All 5 verified real before fixing; none removed.

- **CORS `expose_headers` missing `X-Request-ID`.** Hive's `CORSMiddleware`
  never listed it, so a server-generated id was sent but invisible to
  cross-origin browser JS -- `response.headers` only exposes the
  CORS-safelisted set. `main.py` now sets `expose_headers=[REQUEST_ID_HEADER]`,
  matching maistro-server's own CORS config for the same header.
- **Hive's log lines never carried `request_id`.** Binding it onto the
  execution context does nothing for a log line unless
  `install_log_correlation()` wraps the handler's formatter; Hive's
  `logging_setup.configure_logging()` called `install_log_redaction()` but
  never that. Now calls it first (redaction wraps correlation, same
  ordering as maistro-core's own `configure_logging`).
- **A manual schedule fire (`POST /v1/schedules/{id}/run`) lost its HTTP
  request id.** `_fire_schedule` unconditionally minted a fresh id via
  `detached_execution_context()`, clobbering the real one
  `RequestIDMiddleware` already bound for `fire_now()`'s caller. Fixed by
  moving the read of ambient context to `fire_now()` itself -- the one
  caller with a trustworthy one -- which now passes it down explicitly;
  `_fire_schedule` no longer reads ambient context at all (it can't safely
  tell a real one from a stray leaked one, since it is *also* reachable
  from the tick loop) and always starts clean, using the passed-in id or
  minting its own.
- **The actual production scheduling path had no correlation root at all.**
  `_evaluate_schedule` delegates to `_evaluate_canonical` -> `admitter.
  admit_due()` whenever a canonical admitter is configured, and never
  reaches `_fire_schedule` in that case -- so the #1063 fix as originally
  pushed only covered the standalone/demo tick path and the manual-fire
  path, missing the path a real deployed Hive actually uses. `ScheduleRunAdmitter.
  admit_due` (`maistro.scheduling.admission`) now mints a fresh detached
  correlation root around each admitted occurrence (a catch-up batch can
  admit several in one call; each is an independent invocation and gets
  its own id) and records it in that Run's provenance under the same
  `request_id` key.
- **An unhandled exception's 500 carried no `X-Request-ID`.** With no
  catch-all exception handler, an exception propagates past
  `RequestIDMiddleware` (`call_next` raises rather than returning) straight
  to Starlette's outer `ServerErrorMiddleware`, which has no way to attach
  an id it never saw. Hive's `main.py` now registers a generic
  `@app.exception_handler(Exception)` that reproduces Starlette's own
  default body/status (`PlainTextResponse("Internal Server Error", 500)`)
  and attaches the header -- only the header is new, nothing about the
  response shape changes.

**Tests.** `test_admission.py` (scheduling, +3): an admitted occurrence
carries its own `request_id`; a stray ambient context bound before
`admit_due` does not leak into the Run; each occurrence in a catch-up batch
gets a distinct id. `test_scheduler.py` (+2): a manual fire preserves the
HTTP request's id; one triggered with no ambient request mints its own.
`test_request_id_middleware.py` (+2): the header is exposed cross-origin;
present on an unhandled exception (a throwaway route registered and
removed within the test). `test_log_redaction.py` (+1): `configure_logging()` installs
correlation and a bound `request_id` reaches a captured log line, following
that file's existing `_reconfigure` harness for the ADR-064 redaction wiring.

Full `packages/maistro-core/tests/`, `packages/hive-conductor/backend/tests/`,
and `packages/maistro-server/tests/` pass (9113 / 2284 / 349). `ruff check`/
`ruff format --check` clean on every touched file. `mypy --strict
packages/maistro-core/src` clean.

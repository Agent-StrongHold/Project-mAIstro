---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/hive-conductor/backend/tests: +1
---
# fix-m1-1063-codex-review-round2

Two more tests answering CI failures on the review-round-1 head, one per
suite. Net delta only -- a same-count rewrite in `c83f0e6` (see below) is
not part of this file's `+1`/`+1`.

**`c83f0e6` (no net count change).** CI's `pull_request`-gating run failed
`test_the_id_is_present_on_an_unhandled_exception` (`assert 200 == 500`)
even though the full local suite passed. The test dynamically registered a
route and relied on an exception handler on the shared `main.app`
singleton every other test in the file (and suite) also touches --
order-dependent on when Starlette's middleware-stack caching interacts
with other tests' requests across the whole session. Extracted
`unhandled_exception_handler` to a module-level function (was nested in
`create_app()`) and rewrote the test to build a small isolated `FastAPI`
app wiring the same middleware + handler, rather than mutating the shared
production object. Same one test, rewritten; the suite's node count does
not change.

**`5af2123` (+1/+1).** The `Coverage gate (publish-set floor + diff
coverage)` job failed: two `if request_id:` branches added in the prior
round -- `main.py`'s `unhandled_exception_handler` and
`ScheduleRunAdmitter._admit_one` -- only ever had their truthy side
exercised (the exception-handler test always ran with `RequestIDMiddleware`
installed; `_admit_one` is only ever called from inside `admit_due`'s own
`detached_execution_context()`, which always binds a fresh non-blank id).
One test per file exercises the false side directly: the handler built
without `RequestIDMiddleware` in an isolated app (no crash, no header
set); `_admit_one` called directly with no execution context bound (the
`request_id` provenance key is absent, not blank -- same discipline as
`schedule_inputs`). Verified with `coverage --branch` that both
previously-partial branches are now fully covered.

Also corrects an arithmetic slip in `fix-m1-1063-codex-review-round1.md`'s
own delta: `test_request_id_middleware.py` gained 2 tests in that round,
not 3 as originally recorded (the prose there miscounted), so this branch's
recorded total for `packages/hive-conductor/backend/tests` was previously
overstated by 1 while `packages/maistro-core/tests` was understated by 1
from the two tests recorded here -- both corrected now, matching
`check-suite-inventory.py`'s drift report exactly (core collected one more
than recorded, hive-conductor one fewer).

Full `packages/hive-conductor/backend/tests/` (2285), and
`packages/maistro-core/tests/scheduling/` + `tasks/` (394) pass. `ruff
check`/`ruff format --check` clean. `mypy --strict
packages/maistro-core/src` clean.

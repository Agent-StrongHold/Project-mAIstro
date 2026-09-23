---
inventory-delta:
  packages/maistro-core/tests: +13
---
# claude-ws-1108-treat-every-spine-failure-after-dispatch-5aa5

#1108: a chat turn's post-dispatch spine failure is classified whatever its
exception type, not only when it is a `RunIntegrityError`.

All thirteen are additions in `packages/maistro-core/tests/runs/test_chat_execution.py`;
nothing was removed or renamed.

- +3: the three existing post-dispatch tests (failed COMPLETED write, failed
  NodeRun reconciliation, dispatch failure whose FAILED write also fails) are
  parametrized over a second, raw-driver exception type (`sqlite3.OperationalError`,
  `ConnectionError`, `OSError`) beside the original `RunIntegrityError`.
- +3: a raw driver failure on the COMPLETED write, run on the shared
  memory/SQLite/PostgreSQL `spine` fixture (PostgreSQL skips without a DSN).
- +1: a raw `OSError` before the dispatch propagates and never reaches the model.
- +1: a runtime deadline that cancels the dispatch still arrives as
  `RuntimeDeadlineExceeded`, not the `CancelledError` the dispatch observed.
- +2: a cancel or a deadline that cuts the dispatch off and whose CANCELLED /
  TIMED_OUT write then fails never lets a bare `RunIntegrityError` escape,
  which the container would read as pre-dispatch and answer with a second
  model call.
- +3 (Codex review): a dispatch that catches the deadline's cancellation and
  answers late still ends as `RuntimeDeadlineExceeded`; an answer behind a
  Run fenced CANCELLED ends the turn cancelled when the fence read fails
  once; and a fence that stays unreadable still hands the answer back once.

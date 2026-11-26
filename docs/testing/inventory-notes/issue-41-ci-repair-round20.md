---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 20: local coverage-gate investigation

No tests were added in this verification-only round. The assigned coverage-gate
failure was not treated as resolved from prior notes: the workflow's
`coverage-unit` producer was run locally after `uv sync --locked --all-extras`.
It did **not** complete in this shared worktree: `pytest-timeout` terminated
five unrelated full-suite scans and 26 archive fixture imports after 30 seconds
while the host was under concurrent-worker load (load average 15.97/19.73/20.94,
with multiple other worktrees' full-core collection/coverage processes using
CPU). The producer exited nonzero after 10,800 passed, 735 skipped, five timeout
failures and 26 timeout errors. This does not identify a #41 source defect and
is not evidence that the CI coverage gate passed; it remains explicitly
unverified for a fresh, uncongested runner.

Focused acceptance behavior did run at this head (`afdcbd21d226`):

- `uv run coverage run --branch --source=packages/maistro-core/src/maistro -m
  pytest packages/maistro-core/tests/tasks/test_replay_receipt_durable_row.py
  packages/maistro-core/tests/tasks/test_idempotency.py
  packages/maistro-core/tests/tasks/test_idempotency_durable.py
  packages/maistro-server/tests/api/test_tasks_idempotency.py -q -x` ->
  **110 passed, 1 skipped**. The changed durable-row replay seam is exercised
  under branch coverage; `tasks/idempotency.py` reports 94% in that scoped run.
- The current #41 task/chat battery (chat admission and chat-to-graph E2E,
  parked-run and spine conformance, in-memory/durable/purge idempotency,
  durable-row replay, task API, and chat API) -> **469 passed, 127 skipped**.
- The shipped Hive chat/task boundary battery -> **117 passed**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> **0**: 1,402 findings,
  all classified and ledgered; no vulture-baseline amendment was appropriate.

The acceptance evidence above confirms task/chat canonical Run behavior, but
the required publish-set floor plus full diff-coverage gate cannot be claimed
from this round. The next verifier should run `coverage-unit`, `coverage-archive`
and `coverage-postgres`, then the `coverage-gate` combine/report/diff commands
on an uncongested runner before declaring the repair merge-ready.

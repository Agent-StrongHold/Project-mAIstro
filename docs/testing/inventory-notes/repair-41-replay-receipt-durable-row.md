---
inventory-delta:
  packages/maistro-core/tests: +4
---

# repair-41-replay-receipt-durable-row

Repair of the #41 verification round's blocking finding: the idempotency
replay `TaskQueue._replay_receipt` early-returned the durable `TaskRecord`
row (ADR-018) before the resume gate, so a replica answering a retry with
only the row in hand returned "queued" while no queue anywhere held the Run —
the exact strand the resume path (record_transition + `_enqueue`) exists to
stop. The row is now the receipt's identity source (#1057) and still falls
through to the gate; only the live in-memory receipt short-circuits.

`packages/maistro-core/tests/tasks/test_replay_receipt_durable_row.py` (+4):
drives `_replay_receipt` directly with a claim record whose task row exists
(a session double mirroring the real `server_default` for `created_at`, so
the rebuilt receipt actually validates) — a combination no prior test
covered, which is why the early-return reproduced at d93d1de7:

1. row-only replay re-enqueues a stranded QUEUED Run (`_pending` and
   `_tasks` populated, principal evidence from the row, Run still QUEUED) —
   this test fails against the early-return;
2. row-only replay with another replica's worker already RUNNING the Run
   answers from the row without enqueueing a second executor;
3. row-only replay with a terminal (COMPLETED) Run answers without
   enqueueing — finished work is not re-run;
4. an unreadable row (ownerless actor evidence) falls through to the
   claim's stored-request reconstruction and still resumes the strand.

Also updated in place, same node count: the pre-existing
`test_a_replayed_admission_after_restart_answers_from_the_durable_delegated_receipt`
now snapshots the row before the retry, because the resumed admission
legitimately re-persists the receipt when it re-enqueues — the row-vs-
request discriminator (`created_at`) is unchanged.

## Executed evidence

- `uv run pytest packages/maistro-core/tests/tasks/test_replay_receipt_durable_row.py
  -x -q` → **4 passed**.
- The focused #41 core acceptance set (chat admission/E2E, Run spine,
  idempotency, durable and purge tiers, and this regression) → **438 passed,
  127 environment-gated skips**.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_idempotency.py
  -x -q` → **13 passed**. This includes the durable timeout/restart replay
  wire scenario.
- Running the idempotency suites under branch coverage and scoring the code
  diff from before the replay repair reports no `tasks/queue.py` diff-coverage
  failure; the regression covers the previously unexercised durable-row path.

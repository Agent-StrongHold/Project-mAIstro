---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# Issue #41 CI-repair round 23: focused acceptance revalidation

No production code or test count changed in this validation-only round.

At `d750b0000b54`, the focused canonical-admission battery passed:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission.py \
  packages/maistro-core/tests/tasks/test_idempotency.py \
  packages/maistro-core/tests/tasks/test_idempotency_durable.py \
  packages/maistro-core/tests/tasks/test_replay_receipt_durable_row.py \
  packages/maistro-core/tests/runs/test_chat_admission.py \
  packages/maistro-core/tests/runs/test_chat_execution.py \
  packages/maistro-server/tests/api/test_tasks_idempotency.py \
  packages/maistro-server/tests/api/test_chat_completions.py -q -x
# 263 passed, 12 skipped
```

The current SIGTERM integration test change also passed (`2 passed, 1 skipped`).
The exact vulture ratchet command reported 1,361 reviewed findings, with zero
unclassified and zero never-allowlisted identities.

The complete publish-set coverage producer and combined/diff coverage judgment
remain unverified locally: `docker info --format '{{.ServerVersion}}'` cannot
connect to `unix:///var/run/docker.sock`, while the `maistro-evolve` coverage
legs require its sandbox. This is not evidence for a source or ledger repair.
The issue snapshot's #1845 task-admission completion-write fault remains a
separate unresolved closeout requirement; this validation did not claim to
repair it.

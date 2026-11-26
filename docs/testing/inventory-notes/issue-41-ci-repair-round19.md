---
inventory-delta:
  tests/: +0
---

# Issue 41 CI repair (round 19): independent acceptance and vulture ratchet verification

No test delta: this is an evidence-only verification note for the assigned
CI-repair round. The only previously reported actionable failure was the
vulture ledger ratchet. It was re-run at the assigned head rather than assumed
from earlier notes.

## Vulture acceptance

```
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'
```

exited 0 at `56b72d783cea4372d2ba4f5f38579981fd7191e4`: 1,403 reviewed
identities equal 1,403 findings, with `unclassified: 0` and `never_allowlist:
0`. No ledger amendment is warranted: there is no new unbanked debt or stale
ledger entry in the actual invocation.

## Independent issue #41 acceptance battery

- `uv run pytest packages/maistro-core/tests/runs/test_chat_admission.py
  packages/maistro-core/tests/integration/test_chat_to_graph_e2e.py
  packages/maistro-core/tests/runs/test_parked_run_resume.py
  packages/maistro-core/tests/runs/test_spine_conformance.py
  packages/maistro-core/tests/tasks/test_idempotency.py
  packages/maistro-core/tests/tasks/test_idempotency_durable.py
  packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py
  packages/maistro-server/tests/api/test_tasks_idempotency.py
  packages/maistro-server/tests/api/test_chat_completions.py -x -q`
  → **462 passed, 127 skipped**. This exercises one-node task/chat admission,
  response `run_id`, scoped replay/concurrency/ambiguous-admission behavior,
  Run lifecycle authority, and session/request provenance.
- `uv run pytest packages/hive-conductor/backend/tests/test_chat_run_admission.py
  packages/hive-conductor/backend/tests/test_api.py
  packages/hive-conductor/backend/tests/test_engine_service.py
  packages/hive-conductor/backend/tests/test_workspace_scoped_submission.py
  -x -q` → **105 passed**. This exercises the shipped Hive task and chat
  boundaries against the embedded canonical Container.

The skipped cases are the suite's optional PostgreSQL tiers; this round did not
set a PostgreSQL DSN, so real-server durable-idempotency execution remains
unverified by this round (the SQLite durable tier did execute).

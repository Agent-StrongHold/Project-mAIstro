---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# Issue #41 CI-repair round 41: independent acceptance and coverage triage

No production code or test identity changed in this validation-only round.

The supplied driver logs do not contain the reported coverage failure: they show
`ruff check`, formatting, focused task/chat tests, and suite inventory only. The
current worktree cannot run the PostgreSQL coverage producer because its required
Docker daemon is unavailable:

```text
DOCKER_HOST=unix:///var/run/docker.sock docker info
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

The workflow's `coverage-postgres` producer requires the service before it can
run migrations and its real-PostgreSQL task-admission coverage legs. This is an
environment block, not evidence for a source or ledger amendment.

Focused, locally reachable canonical-admission behavior was re-executed:

```text
uv run pytest packages/maistro-server/tests/api/test_chat_completions.py \
  packages/maistro-server/tests/api/test_chat_completions_gate.py \
  packages/maistro-core/tests/test_container_chat_runs.py \
  packages/maistro-core/tests/tasks/test_idempotency.py \
  packages/maistro-core/tests/tasks/test_idempotency_durable.py \
  packages/maistro-core/tests/tasks/test_admission_commit_atomicity.py \
  packages/maistro-server/tests/api/test_tasks_idempotency.py -q -x
```

It passed: **210 passed, 1 skipped**. The required exact vulture invocation
also passed: **1,342 reviewed identities -> 1,342 findings**, with zero
unclassified and zero never-allowlisted identities. `ruff check .` and
`ruff format --check .` passed.

The dispatched issue snapshot records #1845 as an open direct residual whose
required real PostgreSQL process-kill/multi-replica proof is still outstanding.
Therefore the parent issue's atomic-admission acceptance remains unproven even
though the reachable task/chat seam passes.

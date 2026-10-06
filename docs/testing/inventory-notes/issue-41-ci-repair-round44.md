---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-canvas/tests: +0
  packages/maistro-evolve/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-bootstrap/tests: +0
  packages/maistro-server/tests: +0
---

# Issue #41 CI-repair round 44: coverage-unit reproduction

No production code or test identity changed in this validation-only round.

The exact `coverage-unit` producer from `.github/workflows/quality.yml` was
re-run at `3fe13229cfb7` after `uv sync --locked --all-extras` and
`uv pip install -e packages/maistro-evolve`. Its core and Canvas legs passed:

```text
packages/maistro-core/tests: 13038 passed, 936 skipped, 1 xfailed
packages/maistro-canvas/tests: 464 passed, 75 skipped
```

The producer then failed in the `maistro-evolve` sandbox tests, rather than in
the issue's task/chat surfaces:

```text
3 failed, 984 passed, 6 skipped
```

All three failures require the Docker sandbox. The direct prerequisite check
also failed:

```text
DOCKER_HOST=unix:///var/run/docker.sock docker info
Cannot connect to the Docker daemon at unix:///var/run/docker.sock.
```

The failures therefore do not establish a source defect in this lane, and no
code or quality-ledger change was made to hide them. A Docker-capable runner
must re-run the complete `coverage-unit`, `coverage-archive`, and
`coverage-postgres` producers plus their `coverage-gate` combine/diff steps to
resolve the reported gate failure.

Reachable task/chat behavior was independently rechecked:

```text
uv run pytest packages/maistro-server/tests/api/test_chat_completions.py \
  packages/maistro-server/tests/api/test_chat_completions_gate.py \
  packages/maistro-core/tests/test_container_chat_runs.py \
  packages/maistro-core/tests/tasks/test_idempotency.py \
  packages/maistro-core/tests/tasks/test_idempotency_durable.py \
  packages/maistro-core/tests/tasks/test_admission_commit_atomicity.py \
  packages/maistro-server/tests/api/test_tasks_idempotency.py -q -x
210 passed, 1 skipped
```

The required exact vulture invocation also passed: **1,336 reviewed
identities -> 1,336 findings**, with zero unclassified and zero
never-allowlisted identities.

The dispatched issue snapshot still records open #1845 as requiring real
PostgreSQL process-kill/multi-replica evidence before #41 closeout. This round
neither claims that evidence nor merge readiness.

---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 47: failure evidence and closeout boundary

The supplied driver evidence does not identify a source-level coverage failure:
`/home/dev/maistro/jobs/d459d5d33269432c8eaba20b2b591fe1/check-1.log`
contains only `All checks passed!`. The supplied focused suite passed `470
passed, 143 skipped`, and all four suite-inventory checks passed. No speculative
coverage or vulture-ledger edit is justified without a failed producer log or a
named uncovered source line.

This is not closeout evidence. The authoritative issue snapshot requires
#1845's real PostgreSQL process-kill, commit-response-loss,
independent-replica/fenced-handoff, canonical Attempt/effect-winner, upgrade,
and owner-disposition proofs. The existing live PostgreSQL test module states it
is short of a process-kill harness and skips when `MAISTRO_TEST_PG_DSN` is not
set. Docker is unavailable in this worker, so neither that required live proof
nor the workflow's `coverage-postgres` producer can be independently executed
here.

## Executed validation at `2f6d56e31`

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed: 1,332 reviewed identities, 1,332 findings, zero unclassified and zero never-allowlisted.
- The focused task admission/idempotency/API seam passed: 125 passed, 1 skipped.
- `uv run ruff check .` and `uv run ruff format --check .` passed.
- The canonical task/chat and one-node-spine battery passed: `uv run pytest packages/maistro-core/tests/runs/test_spine_conformance.py packages/maistro-core/tests/runs/test_wiring.py packages/maistro-core/tests/test_container_chat_runs.py packages/maistro-server/tests/api/test_chat_completions.py packages/maistro-server/tests/api/test_chat_completions_gate.py -q -x` → 367 passed, 119 skipped.
- `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/tasks/test_pg_admission_atomicity_live.py -q -x` collected two tests and skipped both because no DSN was configured. `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` failed because the daemon was unreachable.

---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 41 repair (round 13): restore the admission seams the develop merge dropped

Delta note: `+0` against the gated `packages/maistro-core/tests` suite —
existing suites re-run as evidence; no new test files were added in this round.

Round scope: resolve the preserved develop sync conflict (base `0d8a90f`,
origin/develop moved 8 commits past the previously merged tip) and repair the
two red CI gates reported at `ca3f1b7d` (Quality: vulture per-identity ledger;
Coverage: diff coverage), against actual local evidence rather than scanner
guesses.

## What the merge had broken, and the fix

The sync merge `9f1723e31` resolved `packages/maistro-core/src/maistro/tasks/admission.py`
by taking the `a71fc2e43` side wholesale (verified: `git diff a71fc2e43 HEAD --
...admission.py` was empty at round start). That silently discarded four seam
methods the *merged* `queue.py` — which is a true union of both lineages —
probes for:

1. `TaskRunAdmitter.admission_scope` and `WorkspaceRoutingAdmitter.admission_scope`
   — the Workspace/Project claim-key binding `_scope_binding` requires. Without
   them the scope fallback read `getattr(admitter, "project_id", "")`, so two
   `TaskRunAdmitter`s bound to different Projects in one Workspace produced the
   same scope key and *replayed each other's Runs*:
   `test_same_key_in_distinct_projects_mints_distinct_runs` failed at the
   pre-repair head (reproduced in a throwaway worktree at `9f1723e31`).
2. `TaskRunAdmitter.run_for_task_receipt` and `WorkspaceRoutingAdmitter.run_for_task_receipt`
   — the #1176 ambiguous-admission discovery seam. Without them
   `RunStore.find_run_by_task_receipt` (protocol, in-memory base, Pg and
   SQLite stores) had no production caller, which is exactly the 4 new
   unbanked identities the vulture ratchet reported (`core-public-api-surface`).

Fix (commit `9468b4d6b`): restore the four methods verbatim from the
`f5def8311` lineage, keeping the `a71fc2e43` semantics the merged queue also
depends on (`TASK_PAYLOAD_KEY` provenance replay, `previous_status`,
single-commit QUEUED creation). No ledger amendment was needed or made: after
the fix the vulture scan is byte-identical to the trusted baseline at
`0d8a90f` — 1405 findings, 0 new — which is the stronger outcome, because the
ratchet requires grants to be read from the base revision, so this branch
could never have authorized the debt itself.

## Validation executed

- `git merge origin/develop` (0d8a90f): clean, committed as the round head.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, "1405 reviewed
  identities -> 1405 findings", no new/unbanked debt.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 385 passed, 15
  skipped; `packages/maistro-core/tests/runs -q` → 882 passed, 210 skipped;
  `packages/maistro-server/tests/api/test_tasks_idempotency.py` → 13 passed.
- Diff-coverage gate reproduced locally per `.github/workflows/quality.yml`
  producers: maistro-core (full suite), maistro-server, hive-conductor
  backend, plus the PostgreSQL producer legs (`tests/migrations`, then
  `alembic upgrade head`, then the persistence/events/runs/graph/projects/
  workspaces/scheduling/purge suites) against a real `pgvector:pg17` container.
  `coverage combine` + `scripts/check-diff-coverage.py coverage.xml --base
  origin/develop` → exit 0: "every measured file this change touches is at or
  above 90% lines / 80% branch arcs". The publish-set 87% floor itself needs
  the full multi-service CI matrix and was not re-measured locally; this
  round's diff adds 48 covered lines to one file, so the aggregate risk is
  the publish set's standing exposure, not this change.
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  clean; `uv run mypy packages/maistro-core/src packages/maistro-server/src`
  → only 5 pre-existing `maistro_bootstrap` import-not-found errors (CI uses
  `--all-extras`; unchanged files).

Known flakes observed while measuring (pass in isolation, unrelated to this
surface): `test_container_postgres.py::test_an_unreachable_server_is_an_error_
not_a_fallback` and `::test_an_unmigrated_database_names_the_command_that_
fixes_it` under full-suite load.

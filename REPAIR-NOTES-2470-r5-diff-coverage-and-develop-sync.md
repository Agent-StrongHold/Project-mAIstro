# 2470 r5 — diff-coverage gate repair + develop sync

Round 5 repair for #2470 (branch `auto-2470`). Starting head `f8451ece986a`;
develop base moved to `27efe169491e` (three new commits: #2492, #2496, #2494).

## The actual CI failure (read from the run's log, not guessed)

At `f8451ece986a` exactly one check failed:
**Coverage gate (publish-set floor + diff coverage)** — and inside it, the step
`Diff coverage gate (per file, lines 90% / branches 80%)`:

- `packages/hive-conductor/backend/routes/eval_judge.py`: **87.4%** of 95 changed
  lines; uncovered 124, 147, 148, 150, 198, 199, 205, 210, 211, 221, 222, 345.
- `packages/hive-conductor/backend/services/dag_run_inspection.py`: **87.5%** of 8
  changed lines; uncovered 540.

The `RuntimeError: Event loop is closed` lines in the same log are a
`PytestUnhandledThreadExceptionWarning` (aiosqlite worker teardown) inside the
*passing* maistro-server producer — warnings, not the failure. The publish-set
87% floor passed (95% total).

## What this round did

1. **Salvaged the previous round's uncommitted work** (backed up first to the job
   directory as `incoming-uncommitted.patch`, then landed): the nine
   "degraded-spine answers and alias-evidence discovery edges" tests in
   `test_eval_judge_scoring_authorization.py` that cover exactly the lines the
   gate named — engine-absent 503, store-less bridge 503, readerless bridge
   scoring through the embedded Workspace authority, embedded-authority
   unavailable 503, error-receipt visibility + retry, alias direct-lookup
   (no sibling-row leak), canonical-keyed read degradation without/with a
   readerless bridge, and discovery's Workspace-universe + blank-id refusals.
2. **Merged `origin/develop`** (`486cc09b83`) — no textual conflicts; verified the
   auto-merge of `services/chat_completion.py` (our provenance change + develop's
   `public_failure` import) is semantically coherent and that
   `quality/route-permissions.json` kept the `/v1/eval-judge` method-split row
   (`git diff origin/develop -- quality/` shows only our intended row change).
3. **Recorded the +9 inventory delta** in
   `docs/testing/inventory-notes/2470-eval-judge-scoring-permission.md`
   (front-matter now `+34`) with prose.

## Local proof (CI's exact commands)

- Full hive-conductor backend suite under coverage, CI's producer invocation:
  `coverage run --branch --source=packages/hive-conductor/backend -m pytest
  packages/hive-conductor/backend/tests --timeout=30 -q` → **4426 passed, 47 skipped**.
- `coverage xml -o coverage.xml` then
  `scripts/check-diff-coverage.py coverage.xml --base 27efe169491e…` (the new
  PR merge base) → **"ok: every measured file this change touches is at or
  above 90% lines / 80% branch arcs"**, exit 0.
- `scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  → **ok: 4473**.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `scripts/check-route-permissions.py` → ok (42 declared, ratchet vs base 27efe16949).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact-debt-ledger, CI's exact args) → exit 0,
  1221 reviewed identities, no ledger edit needed.
- Merge seams: `pytest packages/maistro-core/tests/runs packages/maistro-core/tests/tasks`
  → 2473 passed; `pytest packages/maistro-server/tests` → 723 passed.
- Manifest battery `pytest test_eval_judge.py test_eval_judge_scoring_authorization.py`
  → 70 passed.

## Not ours to fix here

The previous round's blocker ("recovery budget exhausted: openrouter
poolside/laguna-s-2.1:free 404") was a provider-availability error in the
agent's own runtime, not a repository defect — no tree change applies.

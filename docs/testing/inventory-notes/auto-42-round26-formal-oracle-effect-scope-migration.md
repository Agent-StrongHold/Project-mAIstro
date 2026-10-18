---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/maistro-server/tests: 0
  formal/: 0
---

# auto-42 round 26 — migrate the #882 formal oracle onto the effect_scope seam

CI-repair round at head 0c1297edc5b967a54b36e23cdefabf7578384acb (the clean
origin/develop sync af799688 merged into auto-42). Two required checks failed
there, both on ONE stale oracle file:

- `Quality gate (Pillars 1–4, 7, 8)` — failed at the
  `Hypothesis property tests (formal/)` step
  (`uv run pytest formal/ --timeout=120 -q`): 3 failed / 664 passed;
- `formal-conformance` — failed at `Run formal models`
  (`pytest formal/models/ -v --timeout=300 --hypothesis-seed=0`): the same
  3 failures (664 passed), so `Run extension lifecycle proof` never ran.

## What failed and why

The develop sync re-imported `formal/models/test_invocation_effect_idempotency.py`
(#882, landed on develop as 9a0cab7cf) against this branch's Invocation seam.
Round 25 already migrated the last *production* consumer of the retired
`logical_effect: bool` keyword; the formal oracle kept it, because on develop
the seam still speaks that dialect:

- develop `InvocationExecutionService.invoke(..., logical_effect: bool)`:
  admission identity widens across NodeRuns when *either* side sets the flag
  (`_same_admission_effect`);
- this branch `invoke(..., effect_scope: str | None)`: the identity is the
  exact persisted scope (`effect_scope or bound-context or node_run_id`),
  bound for Graph nodes by `bind_logical_effect_scope` (#1194).

So every oracle call raising `logical_effect=` died with
`TypeError: InvocationExecutionService.invoke() got an unexpected keyword
argument 'logical_effect'` — `TestInvocationEffectMachine` (2 sub-failures),
`test_completed_logical_effect_replays_without_redispatch`, and
`test_ambiguous_outcome_blocks_until_evidence`. The machine's
`race_duplicate_logical_effect` assertion (`expected exactly one dispatch,
saw 0`) was a knock-on: both racing workers raised the TypeError before any
dispatch.

## The repair

API migration only — the documented invariants (the oracle's contract) are
untouched:

- `logical_effect=True` → `effect_scope=RUN_ID` (a Run-stable scope keys the
  admission on the Run, invariant 4); `logical_effect=False` →
  `effect_scope=<node_run_id>` (ordinary effects stay scoped to their
  NodeRun visit).
- `test_ambiguous_outcome_blocks_until_evidence` gives *every* invoke in the
  scenario (and its history read) that same Run-stable scope: the new API has
  no either-side widening, so the APPLIED branch's cross-NodeRun replay from
  NODE_B is only a replay — and the dispatch counters only freeze — if all
  five invokes admit under one identity.

No production code changed; `formal/fixtures/security_oracle.json` is
untouched, so `check-formal-oracle-independence.py --base af799688` stays OK
and the M1 convergence freeze reports no new island.

## Validation (CI's exact commands, local)

- `pytest formal/models/ --timeout=300 --hypothesis-seed=0` → **667 passed**
  (was 664 passed / 3 failed), against a fresh Postgres 18.6 database with
  `alembic upgrade head` applied — the formal-conformance recipe end to end;
- `PYTHONPATH=packages/maistro-core/src uv run pytest formal/ --timeout=120
  -q` → **667 passed** — the Quality gate's failing step;
- `python scripts/extension_lifecycle_proof.py --out /tmp/lifecycle-proof` →
  PROVED 10/10 stages, 42/42 checks (the step CI skipped);
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1328 reviewed identities matched, exit 0 —
  no ledger amendment needed;
- `uv run ruff check .` / `uv run ruff format --check .` → clean;
- `scripts/check-suite-inventory.py --suite formal/` → ok, 667 collected =
  recorded (this round adds no tests; delta 0 by construction);
- `scripts/check-execution-lifecycles.py` → OK, 19/19 classified.

Environmental note: the shared local Postgres (`maistro_test`) is stamped at
migration 061 from another lane's in-flight branch, which this head cannot
locate; validation used a dedicated `maistro_formal_auto42` database instead
of re-stamping the shared one.

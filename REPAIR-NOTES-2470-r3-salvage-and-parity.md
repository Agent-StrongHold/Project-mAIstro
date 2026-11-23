# 2470 round 3 — cross-workspace evidence read + single-flight cancellation salvage

Branch `auto-2470` @ `2cf04b2c73` (develop-merged head; base `c810c956785b`).
This round resolves the block left by the provider-death verify round: the
uncommitted worktree salvage (4 files) is inspected, red/green-proven,
validated, and committed. No GitHub mutations.

## Salvage provenance

The round started with 2 modified files visible (`routes/eval_judge.py`,
`test_eval_judge_scoring_authorization.py`); two further files
(`services/eval_judge.py`, `test_eval_judge.py`) were written by the prior
attempt shortly after the round began (mtimes 17:45–17:57 local). All four
were preserved, reviewed, and validated together — nothing was discarded.

## Salvage 1: alias-proven canonical-keyed evidence on GET (read-side twin)

`routes/eval_judge.py` — `read_verdict`'s alias fallback previously served
`get_verdict(detail["canonical_run_id"])` whenever a projection-id read
missed. But a projection row cross-linked to a canonical Run filed in
another Workspace stays visible in its own Workspace by design (the
inspection overlay leaves cross-linked rows untouched), so the committed
fallback leaked W2-keyed verdict evidence through a W1 row the caller can
read — a #1174 non-disclosure break in the evidence surface this issue
protects.

The salvage adds `_canonical_keyed_verdict`: the alias is honored only when
the scoped reader admits the caller to the canonical Run itself AND the Run
is filed in the projection row's own Workspace (the exact association rule
the POST gate applies in `_canonical_scoreable_run`). Every refusal
degrades to the ordinary "no verdict" answer.

Test: `test_cross_workspace_link_cannot_serve_canonical_keyed_evidence`
(scoring-authorization file). Red/green proven: at committed `2cf04b2` with
only the test applied, the W1 row read returns **200 with the foreign W2
verdict**; with the fix it returns the non-disclosing 404
`{"detail": "no verdict for run_id"}`, while the same-Workspace twin row
still serves the alias.

## Salvage 2: the shared scoring invocation survives its callers

`services/eval_judge.py` — the single-flight registry had two cancellation
holes in the "one logical score" contract:

- A joiner's `await leader` was unshielded: cancelling one joiner cancelled
  the shared leader (and every other joiner), dropping evidence after a
  started model call. Now `asyncio.shield(leader)`.
- The leader released the registry in a caller-scoped `finally`: cancelling
  the leader's caller mid-await popped the entry while the shared task kept
  running, so the next caller started a **second paid invocation**. Release
  now rides a done-callback on the scoring task itself, and the leader's
  await is shielded the same way.

Tests (test_eval_judge.py, both red/green proven at `2cf04b2`):

- `test_score_run_joiner_cancellation_does_not_cancel_shared_invocation` —
  joiner cancelled → leader completes, verdict persisted, exactly 1 call.
- `test_score_run_leader_cancellation_keeps_registry_until_finish` —
  leader's caller cancelled → entry survives until the task finishes →
  next caller joins it (still 1 call); registry empty after settle.

## CI gate `cross-product-parity` — failure is a develop-wide flake, not this branch

The merge-queue evaluation failed `cross-product-parity` at head `2cf04b2`:

- `test_builders_required_scenario_emits_strict_closeout_evidence` —
  `ValueError('no active connection')` (aiosqlite worker stopped) raised
  inside `RunExecutionService.cancel_run` and translated by
  `routes/dag_runs.py`'s `except ValueError` into a lying 404; the parked
  turn's settlement then also died with `sqlite3` closed-database errors.
- **Cross-branch evidence**: PR auto-1242 (unrelated diff) failed the same
  test at the same position 6 minutes later with the same signature
  (`Cannot operate on a closed database` + `no active connection`, Task-16
  `CanonicalInteractiveTurnExecutor.execute()`).
- Locally the exact CI command
  (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  tests/cross_product_parity -v --tb=short`) passes 7/7 consecutive runs at
  both the committed head and the salvage state; develop CI at the merge
  base `c810c956785b` is green; this branch touches nothing under
  `tests/cross_product_parity/` or `packages/maistro-core/`.
- Verdict: intermittent CI-runner sqlite/loop lifecycle flake in the parity
  scenario (develop-owned surface). No speculative "fix" was made here —
  the observed route-level 404-conflation lives in the #2466/#1169 cancel
  seam outside this issue's scope and is recorded as the finding.

## Validation battery (this round, salvage state)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest packages/hive-conductor/backend/tests -q` — **4363 passed,
  46 skipped** (develop baseline 4360 + 3 salvage tests).
- `scripts/check-route-permissions.py` — ok (42 declared, 0 undeclared).
- `scripts/check-api-route-contracts.py` — ok (306 handlers).
- `scripts/check-test-duplicates.py` — ok.
- `scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` — ok after the inventory note
  moved to `+23` (prose corrected from the stale "17" to 23 with the
  follow-up sections).

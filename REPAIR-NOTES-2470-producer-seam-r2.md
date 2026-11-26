# 2470 round — producer-seam salvage (r2)

Branch `auto-2470` @ `5965db2dd7` (the #2470 fix commit). This round resolves
the block left by the provider-death rounds: the uncommitted salvage in
`test_eval_judge_scoring_authorization.py` (three tests, tests-only) is now
backed by the production seam it names, plus full validation.

## What was salvaged and completed

The previous attempts left three uncommitted tests pinning the producer half
of #2470's "one logical score" semantics, with no production support:

1. `test_automatic_chat_score_and_manual_retry_are_one_logical_score` — the
   chat producer's automatic score must key evidence by the canonical Run the
   facade result names (`run_id`, #35/#1332), so the route's idempotency guard
   sees it; a later authorized retry pays for no second model call and the
   store holds exactly one evidence row.
2. `test_durable_alias_keyed_verdict_is_honored_without_a_second_paid_score` —
   a valid verdict recorded (pre-canonical keying) under the projection alias
   is honored verbatim by the POST after the same mutation gate: no second
   paid score across an upgrade, no rewrite, no duplicate row.
3. `test_chat_producer_records_the_canonical_actor_and_scope` — the automatic
   score carries the same actor/Workspace/evaluator-version provenance a
   manual score records.

## Production changes (this round)

- `services/chat_completion.py` — `_ChatDagRunScoreAdapter` keys by
  `result["run_id"]` (exec id backstops pre-correlation callers);
  `_eval_judge_score` accepts `actor_id`/`workspace_id` and passes
  `canonical_run_id` through to `score_run`; the `_tool_run_workflow` call
  site rides the turn's `user_id`/`workspace_id` through as provenance.
- `routes/eval_judge.py` — POST idempotency: after the mutation gate and
  terminality, a valid verdict under the requested projection alias is
  returned verbatim (mutates nothing) when the canonical key holds none.
- No authorization/registry changes: `services/authorization.py` is
  byte-identical to HEAD (a red-control mutation was applied and exactly
  restored during this round).
- `docs/testing/inventory-notes/2470-eval-judge-scoring-permission.md` —
  delta +17 → +20 with the seam rationale.

## Red/green evidence

- Before the production change: the three salvage tests failed
  (`TypeError: _eval_judge_score() got an unexpected keyword argument
  'actor_id'` and the keying/idempotency assertions). After: 20/20 pass.
- Issue's negative-test requirement: with the `eval.score` POST registry
  entry removed and the GET carve-out reverted (temporary mutation),
  `test_registry_distinguishes_read_from_scoring` and
  `test_scoring_post_requires_capability_while_reads_stay_scoped` fail; the
  peer-member route test still refuses 404 via the canonical mutation gate
  (defense in depth survives the registry revert). Restored byte-identical.

## Gates run this round

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass (3629 files).
- `uv run pytest packages/hive-conductor/backend/tests -q` — 4360 passed,
  46 skipped (full backend suite, one process).
- `python scripts/check-suite-inventory.py` — ok after the +3 note update.
- `python scripts/check-route-permissions.py` — ok (42 declared).
- `python scripts/check-model-egress.py` — ok (no new effect sites).
- `python scripts/check-api-route-contracts.py` — ok; `check-test-duplicates.py` — ok;
  `check-cross-package-imports.py` — ok.
- Coverage (json, full backend suite): every added line in
  `routes/eval_judge.py` (213–215) and `services/chat_completion.py`
  (1661, 1684–1700, 1836–1840) is covered.

## Residual notes

- Branch is 1 ahead / 2 behind `origin/develop` (dependency bumps on the
  remote); no develop-sync conflict was part of this block, so no merge was
  performed here.
- Chosen, documented semantics unchanged from the fix commit: no automatic
  re-score/supersede, no evaluator-delegation authority (M2 policy owns
  both); the in-flight registry stays process memory with the persisted
  verdict as the post-restart guard.

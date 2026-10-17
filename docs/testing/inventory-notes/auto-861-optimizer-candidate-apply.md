inventory-delta:
  tests/: +14
---

# Issue #861 — optimizer candidate/promotion contract (M4-A)

Adds `packages/hive-conductor/backend/tests/test_optimizer_candidate_apply.py`
(14 tests) pinning the optimizer's application half onto the canonical
candidate/promotion semantics (ADR-082926-65bf / SPEC-081226-bb3a AC-11, the
#116 contract):

- an accepted optimizer proposal becomes an immutable candidate
  `GraphTemplate` version registered through the single reviewed projection
  (`template_adapter.snapshot_to_template`) and promoted via
  `promote_audited` with a `PromotionApproval` naming the accepting human;
  exactly one new active version is created with full provenance (source
  content hash, candidate hash, evaluator version, resulting active version
  recorded on the proposal), and historical versions stay addressable across
  successive promotions;
- verdict/evaluator output cannot mutate production DAG state: scoring writes
  nothing, and the only write on acceptance is the promoted candidate content;
- the wrong-DAG verdict fallback is rejected: `_collect_eval_verdicts` returns
  only verdicts naming the DAG under optimization, so a foreign verdict can
  never surface as a proposal;
- truthful apply outcomes: `applied` only after the candidate version
  actually promoted and the descriptor synced; `no_op` (identical candidate
  content), `unsupported` (no concrete target value — the old fake
  `auto_applied` path), `stale` (source-hash binding no longer holds; the
  human edit survives), `escalated` (execution-tier requests, which never
  mutate the DAG and never write an approval stamp), and `failed` (promotion
  failure compensates back to `candidate`, leaving the prior active Graph
  byte-identical);
- an unmeasured latency p95 is absent, not zero: contributes nothing without
  crashing the old `None > threshold` comparison, with the measured count
  surfaced beside it (ADR-083026-a91e), while measured slow p95 still scores.

Also updates `test_optimizer.py` where tests pinned the removed fake-apply
behavior (`apply_auto` marking valueless proposals applied; synchronous
`record_decision`), and adds a source-level guard that no code path writes a
tier approval stamp (`tier_approved_by`).

## Repair round additions

The repair round restored this file's implementation (lost to a salvage
accident that emptied `services/optimizer.py` and left this suite untracked)
and added 11 tests here plus 10 in `test_optimizer.py` covering the remaining
outcome vocabulary (store unreadable / CAS-1 stale / projection refused /
registration refused / descriptor-sync failure / CAS-2 compensation and its
failed rollback), the engine-container template-store bridge, and the
authorized-Workspace binding of candidate registration (proposals carry the
Workspace the triggering request was authorized against; `commit_candidate`
registers there, not in the configured default — completing the
`routes/optimizer.py` change whose `run_optimizer(workspace_id=...)` half had
been lost). `apply_auto` of an authorization kind now records an escalation
request on the auto path too (pending, never applied) — the same treatment
the accept path already had.

## Validation (this branch)

- `uv run pytest packages/hive-conductor/backend/tests -q`: 2949 passed,
  6 skipped.
- `uv run ruff check .` and `uv run ruff format --check .` clean on touched
  files; `packages/hive-conductor` backend tree clean under `ruff check`.

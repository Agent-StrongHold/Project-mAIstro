---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
---

# Issue #2501 — optimizer auto-promotion is gated on completed independent validation

Implementation record for [#2501][1] (`[M4-A][P2] Gate optimizer auto-promotion
on completed independent validation, not post-apply filtering`), lane
`auto-2501-2501-gate-optimizer-auto-promotion-on-completed`, base
`ab19f5dd5909533fc85a4c65eeb14ac764c4342f`. Every number below was produced in
the lane worktree with `uv run`; nothing is taken from an earlier claim.

[1]: https://github.com/Agent-StrongHold/Project-mAIstro/issues/2501

## The defect, reproduced at the base before any edit

New suite `packages/hive-conductor/backend/tests/test_optimizer_promotion_gate.py`
(18 node IDs) copied onto the untouched base `ab19f5dd`:

```
uv run pytest packages/hive-conductor/backend/tests/test_optimizer_promotion_gate.py -q --tb=line
18 failed
```

The headline failures are the issue's own symptom, observed through the real
ASGI route (`admin_client` → `POST /v1/optimizer/{dag_id}/run?…`):

| test (route level) | failure at base | meaning |
|---|---|---|
| `test_worse_candidate_is_not_promoted_through_the_route` | `assert 1 == 0` on `body["auto_applied"]` | a candidate scored 5 against an incumbent scored 10 was **promoted** |
| `test_unavailable_baseline_is_typed_never_zero_and_blocks_promotion` ×4 (exception, timeout, missing Binding, billing refusal) | `assert 1 == 0` | an unmeasurable incumbent (silently `0.0`) still let the candidate promote |
| `test_validate_false_cannot_skip_policy_required_evaluation` | `assert 1 == 0` | `apply_auto=true&validate=false` promoted without any evaluation |
| `test_concurrent_runs_share_one_paid_evaluation_and_yield_one_winner` | 0 `retry_count_tune` rows in the response | the already-applied proposal was filtered out of the response that reported it applied |

## The change

One optimizer pass is four ordered operations; nothing is activated before
the operation before it completed.

| Operation | Owner | What changed |
|---|---|---|
| 1 propose | `services/optimizer.py::run_optimizer` | applies **nothing**. A concrete AUTO_APPLY candidate is `staged` with its content hash (`staged_candidate_hash`). Kinds that never depend on evaluation keep their classification (`unsupported`, `escalated`). |
| 2 evaluate | `services/optimizer.py::evaluate_staged_proposals`, `services/validation_gate.py::measure_baseline/score_variant` | the exact incumbent is measured first as typed evidence (`ScoredRun`, `available`/`unavailable` + reason + Run/judge-Run/Invocation/evaluator-version/usage lineage). Unavailable ⇒ **nothing is compared**: no variant runs, no hill-climb, every candidate `unevaluated`. The candidate is measured as the exact snapshot a promotion would commit. Identical content in flight is measured once. |
| 3 approve | `services/optimizer_candidates.py::promote_evaluated_candidate` → `PromotionContract.evaluate` (ADR-100126-a9c4, the #116 authority) | evidence must cite Runs + evaluator version; authority ≠ authoring path (`optimizer`); base still current by content; content is a change. |
| 4 promote | `commit_candidate` under a per-DAG `asyncio.Lock` | only an approved candidate reaches it; the minted version is bound to the approval; refusals name `competing_version` (CAS evidence). The contract record is appended to its ledger only after the transition committed. |
| route | `routes/optimizer.py::trigger_optimizer` | `propose → evaluate → approve+promote`, in source order. The `except Exception: baseline = 0.0` fallback is gone. |

Public surface changes (additive unless noted):

- `baseline_score` is `null` when the incumbent is unmeasurable (was a
  synthetic `0.0`); new `baseline_status`, `baseline_detail`,
  `baseline_evidence`.
- `result.proposals` now keeps **every** staged proposal with its verdict
  (`validation.status`, and `variant_b_score`/`baseline_score`/`improvement`
  when measured) instead of silently dropping the ones that did not improve.
- `apply_outcome` gains `staged`, `unevaluated`, `not_improving`; new
  `staged_candidate_hash`, `competing_version`, `promotion_record_id`.
- `run_optimizer(apply_auto=True)` on its own stages and promotes nothing
  (`auto_applied` is always `0`; the gated pass sets the real count).
- `services/benchmark_eval.py` stamps `evaluator_version`
  (`BENCHMARK_EVAL_VERSION = "benchmark-eval/1"`) on every score, so the
  evidence fence reads the evaluator's own version.
- `validation_gate.validate_and_filter_proposals` is replaced by
  `validate_proposals` (annotates, drops nothing).

Reconciliation with accepted authority: the **human** accept path
(`record_decision`) is unchanged — the accepting user remains the approver of
record under #861 and no machine evidence is required of them. Only the
optimizer's own `apply_auto` path is routed through the contract
(SPEC-100126-a9c4: "any new promotion path built for [a family] must route
through the contract").

## Tests

New file (18 node IDs): route level through the real app — worse candidate,
four unavailable-baseline shapes, missing evaluator, `validate=false`,
improving candidate promoted once with full lineage and v1 still addressable
after v2, two concurrent runs (one winner, one explicit `stale` loser with
`competing_version`, candidate judged once, one committed audit entry),
source-order pin; store level — staging applies nothing, three
incomplete-evaluation shapes, self-approval refused, promotion failure leaves
the incumbent untouched and the ledger empty; evaluator version.

Two existing tests were updated because they pinned the replaced behavior:
`test_retry_count_auto_apply_commits_and_reports_applied` (asserted that
`run_optimizer(apply_auto=True)` promotes by itself — the defect) now drives
propose → evaluate → promote and asserts the staged state first;
`test_run_endpoint_validates_proposals_against_a_real_baseline` (its fake
evaluator returned a bare `{"total": 10}`, i.e. exactly the lineage-less score
the gate now refuses, and it asserted the filtered list) now returns lineage
and asserts every row carries a typed verdict.

### Red before / green after

```
# red (base ab19f5dd, new file only)
18 failed

# green (lane head, targeted)
uv run pytest packages/hive-conductor/backend/tests/test_optimizer.py \
  packages/hive-conductor/backend/tests/test_optimizer_candidate_apply.py \
  packages/hive-conductor/backend/tests/test_optimizer_promotion_gate.py \
  packages/hive-conductor/backend/tests/test_property_substrate.py \
  packages/hive-conductor/backend/tests/test_governed_model_consumers.py -q
136 passed
```

### Negative control — swapping the order fails

With the route's operation-2 block moved after the operations-3/4 block
(promote before evaluate) in place, then byte-restored (sha256 verified):

```
4 failed, 14 passed
  test_worse_candidate_is_not_promoted_through_the_route
  test_improving_candidate_is_promoted_once_with_full_lineage
  test_concurrent_runs_share_one_paid_evaluation_and_yield_one_winner
  test_route_orders_evaluation_before_promotion_in_source   (assert 15 < 14)
```

### Whole backend suite

```
uv run pytest packages/hive-conductor/backend/tests -q --timeout=120 -p no:logging
4615 passed, 121 skipped, 58 errors
```

All 58 errors are `fixture 'caplog' not found` caused by this run's
`-p no:logging` (it disables the plugin that provides `caplog`); they are in
unrelated files and are not failures of the change. There are 0 failed tests.

## Gates run locally (CI's arguments; `RATCHET_BASE_REV=origin/develop`)

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | All checks passed / 3733 files already formatted |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1217 → 1217 findings (no candidate change) |
| `check-radon-baseline.py` | 124 → 124 |
| `check-workspace-retirement.py` | OK: 89 entries match the tree (no importer gained or lost; `routes/optimizer.py` still reads `stores.dags`) |
| `check-reachability.py`, `check-reachability-provenance.py` | ok |
| `check-shipped-surface-truth.py`, `check-api-route-contracts.py`, `check-route-permissions.py`, `check-public-routes.py` | exit 0 |
| `check-owned-store-access.py`, `check-agent-store-writes.py`, `check-model-egress.py` | exit 0 |
| `check-promotion-surface.py` (+ provenance), `check-ratchet-provenance.py`, `check-citation-status-provenance.py` | exit 0 |
| `check-suite-inventory.py` | ok with this note's `+18` |

No ledger under `quality/` was edited.

## Acceptance (issue checklist) → evidence

| # | Criterion | Status |
|---|---|---|
| 1 | `validate=true&apply_auto=true` with a worse/failed result: active version unchanged, nothing accepted/applied, no promotion audit, no false `auto_applied` | **PASS** — `test_worse_candidate_is_not_promoted_through_the_route`, `test_unavailable_baseline_…` ×4 (route, real app) |
| 2 | Positive: independent score improves, comparison and policy pass; exact version promoted once; Run/evaluator Invocation/cost lineage recorded; prior version addressable | **PASS (plumbing)** — `test_improving_candidate_is_promoted_once_with_full_lineage`: audit order attempt → committed → apply, `evidence.evaluation_run_ids`, contract `trace(…, 1)` with policy id and prior hash, v1 byte-identical after v2. Lineage comes from faked executor/evaluator seams shaped like the canonical ones. |
| 3 | Baseline exception, missing evaluator, timeout, billing refusal, missing Binding, `validate=false` create no unvalidated active version; no fake 0.0 | **PASS** — route tests above + `test_missing_evaluator_…`, `test_validate_false_…` (`baseline_score is None`, 0 candidate evaluations) |
| 4 | Two concurrent calls, same source: one winner or explicit loser, immutable CAS evidence, no duplicate paid eval | **PASS (in-process)** — `test_concurrent_runs_share_one_paid_evaluation_and_yield_one_winner` |
| 5 | Consumer sees truthful result: response, persisted decision, candidate status and `auto_applied` agree | **PASS** — asserted in tests 1, 2 and 4 (`stores.optimizer_proposals[id]` vs response) |
| 6 | Red-before / green-after route and store tests under canonical PostgreSQL and configured provider; exact SHA; CI evidence; order-swap test fails | **PARTIAL** — red/green at exact SHAs and the order-swap control are above; **UNVERIFIED**: PostgreSQL-backed stores (the suite's stores are the in-memory `JsonStore`s), a configured model provider (no credentials in this environment; executor/evaluator are faked at their module seams), and hosted CI (this lane cannot push). |

## Residual risks

- The promotion lock and the in-flight measurement dedup are **per process**.
  Across replicas the CAS checks still refuse a moved base, but two replicas
  could each pay for the same evaluation and each write a promotion *attempt*
  audit entry before one loses at CAS-1; a durable single-flight/lock owner
  would be a follow-up.
- The contract ledger is process-local until a store adopts it
  (SPEC-100126-a9c4 records template ledger adoption as follow-up); the
  audit log carries the same evidence durably.
- Hill-climb "winners" are still returned unpersisted (pre-existing); they
  are judged only against a measured incumbent now.
- A human accept of a `not_improving` proposal still promotes under #861
  authority (the human is the approver); that is the existing product
  contract, not changed here.

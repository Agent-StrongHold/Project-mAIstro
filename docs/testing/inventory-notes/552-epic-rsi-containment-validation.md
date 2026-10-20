---
inventory-delta:
  packages/maistro-rsi/tests: +40
---

# 552 epic M5-B: RSI containment validation + canonical convergence (#50)

Lane for epic #552. First pass validated containment at base c5e070d97;
re-validated after merging origin/develop `ab8b3737f` (merge `6912141b0`,
+364 commits of child-issue work); this pass implements the epic's
"canonical convergence" exit criterion (#50) on top: RSI campaigns now
execute as canonical Run/NodeRun/Attempt work, consume the generic M3
work-source contracts, and gate kept promotions through the shared M4
promotion contract — as a downstream consumer, never a second authority.

## What this pass adds (issue #50, epic exit criteria)

- `packages/maistro-rsi/src/maistro_rsi/canonical_provenance.py` —
  `RsiCycleProvenance`: admit/run/record one RSI cycle as one canonical
  Run/NodeRun/Attempt in an authorized Workspace/Project (modeled on
  Canvas's `canonical_execution.py`). Includes the #1572 Goal binding
  through `RunStore.create_run` (the service wrapper drops it), idempotent
  admission per cycle id, and a `wrap_executor` seam so the autorun
  coordinator's existing executor gains canonical identity without a second
  scheduler.
- `packages/maistro-rsi/src/maistro_rsi/work_source.py` — `RsiWorkSource`:
  the #98/#100/#101 consumption half. Objectives are selected and claimed
  through the authorized `AgentBacklogSurface` (never the store directly),
  receipts are filed into the generic `BacklogHistoryStore` as Run
  references, discovered work is proposed back as new PROPOSED items with
  `source="rsi"`, and closure requires evidence refs (a completed Run alone
  is never closure evidence, ADR-082426-19ed).
- `packages/maistro-rsi/src/maistro_rsi/promotion_contract.py` — the shared
  M4 contract (#116): kept promotions are gated and minted through
  `maistro.governance.promotion` with the CODE scope's protected
  constituents being exactly #109's `EVALUATOR_ORACLE_PATTERNS`; no
  canonical evaluation Runs or evaluator versions ⇒ no shared record
  (fail-closed, never fabricated).
- Wiring: `autorun.py` (`run_autonomous(provenance=…, work_source=…)`;
  refuses `work_source` without `provenance`; a stall intervention's
  reviewer directions are proposed back into the generic backlog as new
  PROPOSED items and journaled against the discovering Run) and
  `local_loop.py` (`LocalRsiLoop(provenance=…, campaign_id=…,
  actor_principal_id=…)`; each executed cycle files its canonical receipt,
  and every promotion review carries a `decision.shared_contract` leg that
  reports recorded/skipped/refused honestly). The work-source seam is a
  public package API (`from maistro_rsi import RsiWorkSource`), so it is
  reachable from any `import maistro_rsi` — not built-but-never-wired.

## Tests added (+40 node IDs, all in packages/maistro-rsi/tests)

- `test_canonical_provenance.py` (12): admission provenance + idempotency,
  Goal binding both-or-neither, run-through-the-spine with durable Attempt
  results, failure propagation with terminal Run/NodeRun, observed-outcome
  receipts (success and failure), sync-facade refusal inside a live loop,
  wrap_executor one-call-one-Run, find_cycle scoping.
- `test_work_source.py` (9): authorized claim ordering, #101 journal
  receipts with Run references, evidence-ref-required closure, release
  keeps the item open, discovered work filed as new rsi-sourced items,
  unwired-history tolerance, deterministic objective text.
- `test_rsi_promotion_contract.py` (11): CODE-scope classification, kept
  promotion minting + mechanical authority ≠ author, refusals for missing
  Runs/evaluator versions, evaluator-oracle edits, self-approval, no-op,
  stale base, version chaining on one subject.
- `test_canonical_convergence_wiring.py` (8): `run_autonomous` refuses
  work_source-without-provenance; improved campaign closes the claimed item
  citing its canonical Run; unimproved campaign releases the claim; the
  full local loop (real git fixture) records every executed cycle as a
  completed canonical Run and its promotion reviews report the shared
  contract honestly (skipped without evaluator provenance, recorded with
  it, refused loudly on an oracle edit).

## Executed and passing (this pass, head of lane branch)

- New tests: `uv run pytest packages/maistro-rsi/tests/test_canonical_provenance.py
  test_work_source.py test_rsi_promotion_contract.py
  test_canonical_convergence_wiring.py` — **40 passed**.
- Regression on the two wired drivers: `uv run pytest
  packages/maistro-rsi/tests/test_autorun.py test_local_loop.py
  test_promotion_review.py test_review_promotions.py` — **102 passed**.
- Containment batteries re-run unchanged (no gate weakened): **147**
  (host-shell/non-production-reachability/quarantine/promotion-review/
  sensitive-paths/regression-judge/argv/spec/gate-helpers), **163**
  (harvest-boundary/export/rate-pacer/fitness/inventory/red-green/
  evolve-bridge/gateway/quota/mutation — test_autorun moved into the
  regression run above), **72** (isolated wrapper/harvest/checkpoint),
  **69** Conductor containment, **220 passed + 3 skipped** child-behavior
  suites (#108/#109/#392/#2043/#2101/#110-partial).
- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run mypy` with CI's exact ten-package argument list — **no issues in
  1048 source files**.
- `uv run python scripts/check-radon-baseline.py` — 0 new, 0 regressed,
  0 stale (137 C-or-worse blocks, unchanged).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact args) —
  1322 findings == 1322 reviewed identities, exit 0.
- `uv run python scripts/check-reachability.py` — no newly unreachable
  module (`work_source` is reachable via the package `__init__` export).
- `uv run interrogate -f 64 packages/maistro-rsi/src` — 68.0% ≥ 64% floor.
- `uv run python scripts/check-suite-inventory.py` — the only drift is this
  note's +40, recorded above.

## Containment half (still proven, prior passes)

- RSI is non-production-reachable: static import freeze on engine packages;
  Conductor confined to two policy-gated files; quarantine + signed
  approval gate promotion; sensitive-path protection; fail-closed regression
  judge; argv-only model arguments; SPEC §3 fail-closed conformance.
- Bandit gate mandatory in fitness; per-gate state/evidence on TraceNote
  (#304/#820); CI-side execution evidence is `scripts/check-gates-ran.py`.
- #804 non-instantiation: `grep -riE "workspace[_ ]agent|goal.?reconcil"
  packages/maistro-rsi/src` — zero hits; this pass adds consumption of the
  generic contracts only, no reconciliation loop of its own.

## Still open for the epic

- The epic's other children (#302–#359/#509/#820 sub-items, #108/#109/#111/
  #114/#392 remainder) are tracked in their own issues; several landed
  upstream via the develop sync and pass here.
- Milestone re-parenting of children is GitHub hierarchy state, not
  verifiable from the repository.

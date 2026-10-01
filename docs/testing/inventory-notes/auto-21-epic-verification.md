---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
  packages/maistro-evolve/tests: +0
---

# Epic #21 (M4-A governed candidate/evaluation/promotion loop) — verification record

Documentation-only verifier note at head `fa3391e5e925e342d6b2a244f29abe058b1b0c13`
(branch `auto-21`, identical to the develop base — zero epic commits exist in this lane).
No production or test code changed. No driver `check-*.log` files existed for this job
(manifest `checks: []`), so every check below was executed fresh.

## Executed at this head

- `uv run pytest packages/maistro-core/tests/graph/test_template_store.py
  packages/maistro-core/tests/graph/test_node_template_store.py
  packages/maistro-evolve/tests/test_population_audit.py
  packages/maistro-evolve/tests/test_rsi_safety.py -q`
  → **145 passed / 58 skipped** (skips are PG/service-gated).
- `uv run ruff check .` → clean. `uv run ruff format --check .` → 2669 files formatted.

## Acceptance status (epic = full chain with truthful evidence, no side path)

**What exists and works (partial):** an audited, policy-gated promotion API exists at
both the template and genome layers — `maistro/graph/templates.py::promote_audited`
(required `PromotionApproval`, attempt/commit audit ordering with a `promoting`
intermediate state; SPEC-081226-bb3a R14/AC-11) and
`maistro_evolve/population.py::promote_audited` (audit + `approved_for_promotion`
human gate). Their suites pass at this head.

**What fails acceptance:**

1. **#854 NOT satisfied at this head.** `PopulationStore.get_champion()`
   (`packages/maistro-evolve/src/maistro_evolve/population.py:116`) is an unfiltered
   max over `fitness_score`; `_promote`/`promote_audited`
   (`population.py:123,187`) check only approval + audit. Executable proof at this
   head: a genome with a **single** fitness sample (0.95) became champion over the
   0.90 active incumbent and `promote_audited` accepted it — `PipelineGenome` has no
   sample-count/evidence/uncertainty fields at all, and the word "incumbent" appears
   nowhere under `packages/maistro-{evolve,rsi}/src`. The fix exists on the
   **unmerged sibling branch `auto-854`** (commits `28a17a9b7`, `4d1a08f9b`,
   `4eb529b33`: `maistro_evolve/promotion.py` with `PromotionPolicy`
   min-samples/min-margin/objective-version pinning) but is **not reachable** here.
2. **#861 NOT satisfied at this head.** Conductor
   `services/optimizer.py:405-406` sets `applied = True` and counts `auto_applied`
   for AUTO_APPLY proposals **without executing any mutation** (the `_apply_*`
   helpers at `:533/:560/:647` run only from `record_decision:488`, and only for
   accepted KIND_TOPOLOGY) — fake-apply evidence, verbatim the defect #861 names.
   Accepted topology edits write `stores.dags[dag_id] = dag` in place (`:676`):
   no immutable candidate version, no content-hash binding, no `promote_audited`,
   prior version not addressable. `_apply_node_field_mutation` swallows conversion
   failures via `contextlib.suppress` (`:533-558`) so silent no-ops report as
   applied; `upgrade_execution_tier` self-stamps `tier_approved_by: "admin"`.
   Core-side, `maistro/graph/optimizer.py:285,326` `optimize()` returns a mutated
   `GraphConfig` copy directly. The fix exists on the **unmerged sibling branch
   `auto-861`** (`296d6e5a6`, `services/optimizer_candidates.py`) — not reachable here.
3. **#110, #112, #113, #115, #116: no implementation commits exist on any branch**
   (`git log --all --grep` per issue; hits were substring false-positives such as
   #1108/#1135/#1156). Specifically: no retrodiction prefilter anywhere
   (`git grep retrodiction` empty on HEAD, `auto-854`, `auto-861`); no candidate
   archive/historical-retention evaluation (only `get_lineage` exists); no
   generator/mutation/operator credit attribution (only node-level TextGrad
   attribution in `maistro_evolve/reflect.py`); no mechanical-vs-judgment promotion
   split (RSI has RLPHD judgment review only, `maistro_rsi/promotion_review.py`);
   no single canonical promotion contract shared across
   Evolve/prompts/skills/code/policy/harness artifacts.

## Verdict

NEEDS-REPAIR. The epic cannot be proven at this head: 2 of 7 children are
implemented on unmerged sibling lanes (`auto-854`, `auto-861`) and 5 of 7 children
have no implementation anywhere. Next: land auto-854/auto-861, then implement
#110/#112/#113/#115/#116 (or the #116 contract that absorbs them), and re-run this
record's battery against the merged head.

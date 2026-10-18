---
inventory-delta:
  docs/testing/inventory-notes: +1
---

# issue-787-m7-exit-condition-verification

Verification evidence pack for milestone #787 (`[MILESTONE M7] Closed-loop
design process`) at worktree `auto-787` = `develop@c5e070d97d07800464972ee2c02
6a4d525ffbb21` (develop base `ab8b3737fa64f8d840f421ef87ca506c509444ff`),
clean tree, 0 commits ahead of base. No tests were added, removed, or moved by
this note; it records a verification pass only.

#787 is a milestone tracker. Its body delegates all implementation to the
live hierarchy: #788 (initiative) → #789 (epic) → leaves #790–#796, each with
its own `feat/m7-a*` branch off `develop`. This lane therefore verifies the
milestone exit conditions against reachable tree content and records the
dispatch state; it does not re-own leaf scope on the milestone branch.

## Exit-condition evidence (tree at c5e070d)

1. **Rubric as first-class versioned ontology object bound to a Goal
   revision — NOT PRESENT.** `packages/maistro-core/src/maistro/ontology/`
   registers no Rubric kind (generic Semantic-facet registry only,
   ADR-036); the only Rubric code is
   `packages/maistro-core/src/maistro/personas/rubric.py` (ADR-060 persona
   scoring), which #787 explicitly treats as a distinct object.
2. **Eval scores on the producing Run/NodeRun/Attempt stream — NOT
   PRESENT.** No eval/score records in
   `packages/maistro-core/src/maistro/runs/model.py`; no sidecar-eval or
   eval-on-Run implementation exists under `maistro/runs`.
3. **Product/game/book as domain packs of one Run — NOT PRESENT.** No
   domain-pack concept in `maistro-core` or `maistro-design` (only
   design-system catalog manifests under
   `maistro_design/systems/catalog/`).
4. **Park / redirect / accept as a HITL fence on waiting NodeRuns — NOT
   PRESENT.** `runs/lifecycle.py` "parks" only in the retry sense; no
   redirect/accept HITL decision transitions exist in `maistro/runs`.
   (M1 precondition #48 HITL-waiting-NodeRuns is itself still open.)
5. **One public proof with inspectable lineage — NOT PRESENT.** No M7
   ADR/spec (no `ADR-092926-7a01`, no design-loop spec under `docs/specs/`);
   the reference in the #990 test docstring is a forward reference to open
   leaf #790.
6. **Evolve/RSI mapped as eval consumers; second scoring authority
   contract-forbidden — NOT PRESENT.** No Rubric-consumer mapping in
   `maistro-evolve`/`maistro-rsi`; the existing guard
   `packages/maistro-core/tests/fitness/test_no_second_design_product.py`
   (13 passed) forbids a second design *product* (#990), not yet the
   eval-authority guard owned by open leaf #796.
7. **No `milestone:M7` issue lacks a canonical parent — VERIFIED where
   captured (GitHub-side).** Captured bodies show #788→#787, #789→#788,
   #790→#789, #796→#789. Bodies of #791–#795 were outside the dispatch
   capture scope: UNVERIFIED here.
8. **Implementation lands on `feat/*` off `develop` (ADR-095); nothing
   merges to `main` — MET for this lane, vacuously.** Branch `auto-787` is
   cut at the develop head; this lane adds no merge and no runtime change.

## Validation executed (baseline, unchanged tree)

- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 2638 files already formatted.
- `uv run pytest packages/maistro-core/tests/ontology -x -q` — 25 passed.
- `uv run pytest
  packages/maistro-core/tests/fitness/test_no_second_design_product.py -x -q`
  — 13 passed.

## Conclusion

The M7 milestone is pre-implementation: every runtime exit condition (1–6)
is absent from the tree, and the only M7-labeled CI artifact is the #990
product-boundary tripwire. Acceptance for #787 cannot be proven at this
head; the work must proceed through leaves #790–#796 on their own
`feat/m7-a*` branches per #788's ownership table.

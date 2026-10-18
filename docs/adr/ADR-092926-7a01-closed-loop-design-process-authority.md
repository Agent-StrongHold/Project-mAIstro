---
id: ADR-092926-7a01
title: "The design loop has one authority: Goal, Rubric, Pack, Fence, and eval-on-Run"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-29
history:
  - status: Proposed
    date: 2026-09-29
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-061
  - maistro-engine#ADR-097
implements: []
related:
  - maistro-engine#ADR-060
  - maistro-engine#ADR-095
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py::test_no_competing_loop_kind_registration
  - packages/maistro-core/tests/fitness/test_no_second_design_product.py::test_no_competing_execution_lifecycle_name
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092926-7a01: The design loop has one authority: Goal, Rubric, Pack, Fence, and eval-on-Run

- **Status:** Proposed
- **Date:** 2026-09-29
- **Issue:** #790 (M7-A1). Initiative #788; parent epic #789; milestone #787.

## Context

M7 (#788) makes Goal → Rubric → Explore → Execute → Evaluate → Refine a
first-class, inspectable loop on the canonical Run. Every prior milestone that
touched this vocabulary got there by consuming an existing owner: Goals belong
to the M1 workspace/product ontology (#458), waiting NodeRuns and their
pause machinery to #48 / #737, the Design Studio surface to #286 / #95, and
persona scoring to ADR-060 / `maistro.personas.rubric`. Nothing in the tree
yet states, as a governed decision, which objects constitute the design loop
and which identities a product or package is forbidden to invent.

The gap is real and has already produced near-misses: the disposable-prototype
failure modes #990 fences in CI (an Atelier app identity, a DesignRun/
EvalRun/VariantStore second lifecycle, client-side loop state) are exactly a
second product and a second runtime growing out of undecided vocabulary. The
#990 suite freezes the *product boundary*; the runtime half — who may claim
the loop's kind namespace — had no named contract at all.

## Decision

The closed design loop is defined on the canonical execution spine
`Goal → Graph → Run → NodeRun → Attempt` and has exactly one authority per
contract object:

1. **Goal** — the loop's steering object, owned by the workspace/product
   ontology (#458). M7 consumes Goals and binds Rubrics to *Goal revisions*;
   it does not replace or re-own Goal.
2. **Rubric** — the scored acceptance object bound to a Goal revision
   (#791 registers it as a first-class ontology kind). It is distinct from
   the persona RubricEval (ADR-060, `maistro.personas.rubric`), which scores
   persona/department templates, and from the CreativeBrief (#774), which is
   the creative projection of a Goal revision — three kinds that stay
   distinct.
3. **Pack** — a domain pack (product, game, book, …) is a Graph/skill pack
   that executes as **one Run** (#793). A pack is content + graph shape, not
   a package identity, a route, or a product.
4. **Fence** — park / redirect / accept are HITL fence decisions made on
   *waiting NodeRuns* (#794), extending the existing pause/waiting machinery
   of #48 / #737. They are not a new pause universe and never bypass the
   Run lifecycle (ADR-097).
5. **eval-on-Run** — evaluation evidence for a loop iteration is written on
   the *same* Run/NodeRun/Attempt that produced the work (#792). Scores live
   in canonical execution records, not in a side store, a client cache, or a
   product-owned verdict table. A failing rubric dimension must be visible
   on the producing Run.

Forbidden, everywhere in the tree:

- a **second product**: no new app/product identity for the loop (no
  Atelier, no "Canvas Studio"); the loop ships inside the Hive Conductor
  Design Studio surface (#286, #95) plus `maistro-core`. The #990 fitness
  suite freezes these product shapes in CI.
- a **second runtime**: no DesignRun/EvalRun/VariantStore or any competing
  execution lifecycle; nothing but `maistro.ontology` registers the loop's
  kind namespace (Goal/Rubric/Run/eval) — enforced by the fitness fence this
  ADR lists under `tests:`.
- a **second evaluator**: Evolve/RSI (#796) and the M4 promotion loop (#21)
  are *consumers* of eval-on-Run evidence, never the in-Run critic.

`maistro_design.engine` remains prompt-stack assembly (ADR-061): loop
execution is Graph/Run, not the DesignEngine calling an LLM.

### Naming reserves

Registering an ontology kind whose slug names a loop noun (`goal`, `rubric`,
`run`, `eval`, and their plain plurals) outside the canonical ontology module
is a competing loop identity. Product packages keep their own vocabularies
for non-loop concepts; Canvas APIs keep capability-specific names (#788 rule
6) as long as product language does not say the loop *is* Canvas.

## Interface

No new public runtime interface in this decision. The governed surfaces are:

- `maistro.ontology` — the sole registration point for the loop kind
  namespace (`register(kind, model)`; #791 lands the canonical Rubric here).
- `packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py`
  — the static fence: production Python outside
  `packages/maistro-core/src/maistro/ontology/` may not call
  `register(<loop-noun>, ...)`.
- `packages/maistro-core/tests/fitness/test_no_second_design_product.py` —
  the product-boundary suite (#990) this ADR adopts as its product-shape
  contract.

## Acceptance criteria

Layered contracts per [`engine#ADR-032`](ADR-032-contracts-as-acceptance-criteria.md):

- **Boundary contracts**: the loop-kind namespace is registered only by the
  canonical ontology module; production code registering a loop-noun kind
  elsewhere fails CI. The canonical execution lifecycle stays
  Run/NodeRun/Attempt; competing lifecycle names fail CI (#990).
- **Behavioral contracts**: land with the waves that build the objects —
  #791 (Rubric kind bound to Goal revision), #792 (scores on the producing
  Run/NodeRun/Attempt), #794 (fence decisions are restart-safe on waiting
  NodeRuns), #793 (two packs share Run identity and differ only by pack
  contract). Those issues carry their own acceptance evidence; this ADR only
  fixes the authority boundaries they build inside.

## Test plan

| Test | Type | Covers |
|---|---|---|
| `packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py::test_no_competing_loop_kind_registration` | `boundary \| unit` | no competing loop-kind registration outside `maistro.ontology` |
| `packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py::test_fence_detects_a_synthetic_competing_registration` | `boundary \| unit` | the fence trips on a synthetic `Goal` registration (guard can fire) |
| `packages/maistro-core/tests/fitness/test_no_second_design_product.py::test_no_competing_execution_lifecycle_name` | `boundary \| unit` | no DesignRun/EvalRun/VariantStore second lifecycle (#990) |

## Dependencies

- `engine#ADR-036` (ontology kind registry) provides the namespace this
  decision reserves.
- `engine#ADR-097` (lifecycle status machine) owns the Run lifecycle the
  fence decisions extend; nothing here adds a status.
- #791/#792/#793/#794 depend on this vocabulary but own their behavioral
  acceptance; #795 (public proof) and #796 (consumer mapping) record the
  end-to-end evidence on the same objects.

## Out of scope

- Registering the Rubric kind itself (#791) and its Goal-revision binding.
- The fence decision state machine on waiting NodeRuns (#794).
- Domain pack contents (#793) and the pack extension cohort (#1614).
- Evolve/RSI consumer guards (#796); this ADR fixes their *boundary* (they
  are consumers) while that issue lands their mapping and enforcement.
- Studio time-travel UI (#1615) and foreign harness nodes (#1613).

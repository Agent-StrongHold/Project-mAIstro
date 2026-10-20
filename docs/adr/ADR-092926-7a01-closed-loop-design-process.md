---
id: ADR-092926-7a01
title: "Closed-loop design process — one Goal→Rubric→Explore→Execute→Evaluate→Refine loop on the canonical object graph"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-29
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-062
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-060
  - maistro-engine#ADR-061
  - maistro-engine#ADR-041
  - maistro-engine#ADR-090226-9c3f
  - maistro-engine#ADR-091726-7c2a
  - maistro-engine#ADR-095
  - maistro-engine#SPEC-092926-7a01
  - maistro-engine#SPEC-091726-7c2a
supersedes: []
blocks:
  - maistro-engine#SPEC-092926-7a01
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-29
---

# ADR-092926-7a01: Closed-loop design process

**Status:** Proposed

*Merge-blocking status:* this ADR is the M7-A1 contract (#790, parent #789). It blocks every
M7 implementation lane (A2–A7): no Rubric persistence, eval wiring, pack, fence, or Design
Studio runtime PR may land on `develop` before this ADR reaches `Accepted`, and the ADR cannot
reach `Accepted` in a lane that also implements onto itself. Ratification is the explicit act
of merging the ADR/spec pair onto `develop`; after that, A2–A7 implement onto it.

## Context

M7 lands a closed design loop: a person states a desired outcome, the system proposes how the
outcome will be scored, produces candidate artifacts, scores them, and refines — without the
person hand-carriying state between tools. Six upcoming lanes (A2–A7 under #790) each touch the
same nouns. Without one accepted contract, each lane grows a local dialect, and within two PRs
there is a second Goal, a sidecar eval store, and a Canvas-shaped product — the exact drift the
convergence program exists to prevent.

The substrate already exists and is accepted:

- The canonical scope hierarchy `Workspace → Project → Goal`, one accountable `Agent` owner per
  Goal, and exact `goal_revision` lineage are frozen in the shared interoperability ontology
  (#458, `docs/architecture/INTEROP-ONTOLOGY-v1.md`, importable as
  `maistro.interop.INTEROP_ONTOLOGY_V1`).
- The one universal execution hierarchy `Run → NodeRun → Attempt → ExecutionRuntime` and its
  lifecycle vocabulary, including `waiting`, are owned by `maistro.runs`
  (ADR-081226-a66b); graphs execute as one `Graph/Run` (ADR-062).
- Human-in-the-loop decisions are decisions on waiting work (#48): a Run parks in `waiting`,
  and a person's decision resumes, redirects, or closes it.
- CreativeBrief is the versioned creative projection of one Goal revision, produced through the
  requirements interview gate (#774; ADR-091726-7c2a, SPEC-091726-7c2a).
- Persona-department scoring (`RubricEval` in `packages/maistro-core/src/maistro/personas/rubric.py`,
  ADR-060) already exists — under that exact name — for persona template quality, and must not
  be confused with a Goal's acceptance rubric.
- Design Studio is the parent creative-production surface (#286, #773,
  `docs/product/DESIGN-STUDIO.md`); Canvas is one tool inside it, and the embedded `/cli/canvas`
  editor route is not the product identity (#95).
- Branching for all of this is `feat/*` off `develop` (ADR-095); the A1 PR is
  `feat/m7-a1-design-loop-adr`.

What does not exist yet is the contract that says which M7 nouns are first-class objects, who
owns each, and — just as important — which look-alike nouns are forbidden. This ADR is that
contract. It freezes the object graph before any runtime PR grows a second product. A2–A7
implement onto it; this PR implements nothing else.

## Decision

### 1. The loop is one Graph/Run

Design is the loop:

```text
Goal → Rubric → Explore → Execute → Evaluate → Refine
        │                                   │
        └───────── refinement re-enters Evaluate until the Rubric passes or a person fences ──┘
```

That loop is **one `Graph` executed as one `Run`** under the canonical execution model — not a
Canvas product feature, not a client-side pipeline, and not a second engine. `Explore`,
`Execute`, `Evaluate`, and `Refine` are nodes (or node groups) inside the Graph; their
intermediate state lives in the Run's `NodeRun`/`Attempt` records like any other graph
execution (ADR-062, ADR-081226-a66b). A loop iteration is graph traversal; it never mints a
new outer execution identity. Hosting the loop in a client while state lives elsewhere is
explicitly rejected.

### 2. The M7 kind table

Every noun below is either a canonical kind under the #458 ontology, an existing canonical
object the loop consumes, or a host/tool surface that owns no execution. Product modules
project these concepts; they may not redefine them (#458 rule).

| Kind | Canonical semantic owner | Canonical identity | What it is — and is not |
|---|---|---|---|
| **Goal** | `maistro.goals` (#458) | `goal_id` + `goal_revision` | The canonical Project-scoped desired outcome. Exactly one accountable Agent owns it at a time. Rubric does not own Goal; CreativeBrief does not own Goal. |
| **Rubric** | `maistro.goals` (Goal-acceptance facet; lands with M7-A2) | `rubric_id` + `rubric_version` | First-class, versioned, machine-scored acceptance object bound to **exactly one Goal revision**. Not the Persona `RubricEval`; not CreativeBrief prose; not the M4 promotion evaluator. |
| **CreativeBrief** | `maistro.agents` brief surface (#774) | brief identity + `brief_version` | Versioned creative projection (audience, channel, constraints, deliverables) of one Goal revision. It guides *how*; it never replaces Goal identity and never owns acceptance scoring. |
| **Pack** | `maistro.goals` pack facet (lands with M7-A6/A7) | `pack_id` + `pack_version` | A versioned bundle (Graph templates + skills + Rubric templates + persona bindings) that specializes the loop for a domain (product launch, game, book). A Pack is data, not a product; it owns no runtime, state, or identity. Canvas is not a Pack. |
| **FenceDecision** | `maistro.runs` (HITL decision on a waiting NodeRun, #48) | `fence_decision_id` | The record of a person's park / redirect / accept decision on a Run sitting in canonical `waiting`. A domain decision record — never a second universal lifecycle. |
| **EvalRecord** | `maistro.runs` (eval-on-Run) | **no minted identity** — keyed by the producing `run_id`/`node_run_id`/`attempt_id` + Rubric version | Scores, per-dimension results, and evidence produced by the loop's Evaluate phase. No sidecar eval identity exists. |
| **Run / NodeRun / Attempt** | `maistro.runs` (ADR-081226-a66b) | `run_id` / `node_run_id` / `attempt_id` | The one universal execution lifecycle. M7 adds kinds *onto* it; it does not add a lifecycle beside it. |
| **Canvas (tool)** | `maistro.capabilities` (render/patch effects as Provider Invocations) | `capability_id`/`invocation_id` | A pixel composition and rendering *tool* on the governed effect chain. Not the loop, not the product, not a Pack. |
| **Design Studio (host)** | host surface — owns no execution | n/a | The parent UI (#286) where people and the Workspace Agent drive the loop. It composes canonical owners; it must not establish a second Goal, execution, or authorization universe. |

The kind names `Goal`, `Rubric`, and `EvalRun` are **fenced**: the first two may be registered
only by their canonical owners on the ontology registry, and `EvalRun` is reserved-forbidden —
a sidecar eval-run kind is exactly the second identity this contract exists to prevent. A
contract test fails if any module registers a competing `Goal`, `Rubric`, or `EvalRun` kind
outside the ontology registry (`packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py`,
SPEC-092926-7a01).

### 3. Goal — one desired outcome, revisioned, under #458

Goal remains exactly what #458 froze it to be: canonical Project-scoped intent, `goal_id` +
`goal_revision`, exactly one accountable Agent owner, accumulated Runs as evidence. M7 adds no
Goal fields in this ADR and no Goal store in any lane: lanes consume `maistro.goals` semantics
(#458) or wait for them. Two disownments are contractual:

- **Rubric does not own Goal.** A Rubric is bound to a Goal revision; passing a Rubric is
  evidence the person's acceptance standard is met, not Goal state. Goal terminality stays a
  Goal-lifecycle concern (invariant 5 of #458: Run/Rubric outcomes are evidence, not automatic
  Goal completion).
- **CreativeBrief does not own Goal.** The brief is a projection for creative work; redirecting
  creative guidance versions the brief, never the Goal.

### 4. Rubric — the scored acceptance standard for one Goal revision

A Rubric is a first-class, versioned object: dimensions, weights, scoring method, and pass
threshold, bound to exactly one Goal revision. It is what the Evaluate phase scores against and
what a FenceDecision's `accept` cites. Three identities it must never be confused with:

1. **Persona `RubricEval` (ADR-060) is not the Goal Rubric.** `maistro.personas`' `RubricEval`
   scores persona/department template outputs against declarative vocabulary criteria. It is
   behavioral quality scoring for persona authoring; it has no Goal binding, no revision
   lineage against a desired outcome, and lives in `maistro.personas`. The shared ontology must
   never let `maistro.personas` own (or lend its scorer to) the Goal-acceptance `Rubric` kind.
2. **CreativeBrief success criteria are prose, not the Rubric.** The brief may carry acceptance
   *interpretation* in prose (#774); at commit time the interview gate's draft feeds a Rubric
   that makes it machine-scoreable. The prose never doubles as the scored object.
3. **The M4 independent promotion evaluator (#21) is not in-Run Rubric eval.** M4's evaluator
   gates promotion of evolved artifacts/capabilities as an out-of-Run authority. The in-Run
   Evaluate phase scores work *inside* the loop against the Goal's Rubric. Same vocabulary
   family, different object, different owner, different path.

### 5. Pack — specializing the loop without forking it

A Pack is a versioned bundle of Graph templates, skills, Rubric templates, and persona bindings
that specializes the loop for a domain. Packs are data under registry/repertoire supply chains;
a Pack cannot register ontology kinds, own workstate, mint identity, or bypass the effect
chain. "Packs are not products; Canvas is not a Pack": any surface that starts owning Goals,
Runs, or eval state has stopped being a Pack and is either a product (out of scope for M7) or a
defect.

### 6. Execute backends sit on the governed effect chain

Canvas, Deck, Builders, and media providers are **tools** of the Execute phase. Each render,
edit, build, or generation effect flows `Capability → Provider → Binding → Invocation` and
leaves a canonical Invocation record — renderers become Providers (ADR-061 cutover direction),
builders pipelines are graphs invoked through the same path (ADR-099 direction). No Execute
backend holds Goal/Rubric/brief state, and none may become a second execution identity: they
own at most product-local editing UX and local draft state, and return to the canonical
Workspace/Project/Goal-revision/run lineage.

### 7. Eval-on-Run — no sidecar eval identity

Every score, dimension result, and piece of evidence the Evaluate phase produces is an
`EvalRecord` **attached to the producing `Run`/`NodeRun`/`Attempt`**, together with the exact
`goal_revision` and `rubric_version` it scored against. This follows the precedent of episodic
memory naming its producing run (ADR-090226-9c3f): evidence remembers where it was made. There
is no `EvalRun` kind, no eval session store, no second eval identity, and no eval record that
outlives its producing execution's provenance. Re-scoring after a Rubric revision appends new
records under the new Run/Attempt; it never edits history.

### 8. Fence — park / redirect / accept are HITL decisions on waiting work

When the loop cannot proceed on its own — the Rubric cannot pass, guidance conflicts, or the
person must choose — the Run enters canonical `waiting` (ADR-081226-a66b) and the decision is a
person's, recorded as a `FenceDecision` on the waiting NodeRun (#48). The decision vocabulary is
exactly three verbs:

- **Park** — hold the Run in `waiting` without resolution; resumption is a later decision.
- **Redirect** — change direction, by target:
  - redirect of the **desired outcome** → a new **Goal revision** (the Goal's why changed);
  - redirect of **scoring** → a new **Rubric version** bound to the *same* Goal revision
    (the acceptance standard changed, not the outcome);
  - redirect of **creative guidance** → a new **CreativeBrief version** bound to the *same*
    Goal revision (the how changed).
- **Accept** — close the loop: the cited Rubric version passed at a cited Goal revision.

**No silent history rewrite.** Redirects create new revisions/versions; they never mutate the
Goal revision, Rubric version, brief version, Run, NodeRun, Attempt, or EvalRecord that already
exists. Every prior Run keeps the exact `goal_revision` / `rubric_version` / brief version it
consumed, recoverable per #458's revision-lineage requirement. A redirect that cannot say which
of the three targets it moves is not a valid redirect — it is three requests and must be
decomposed before commit.

### 9. Consumers — M4 and M5 read evidence; they do not join the loop

M4 (#21) and M5 (#552) may **consume** M7 `EvalRecord` evidence as one input to their own
contracts (promotion, evolution). Neither may become the in-Run critic, inject evaluation into
a live Run, or provide a second promotion path for design artifacts. Promotion remains M4's
contract; the loop's acceptance remains the Goal Rubric's.

### 10. Host surface — Design Studio hosts; tools do not define the product

Design Studio is the parent surface (#286, #773): the person and the Workspace Master
Orchestrator drive the loop there. The embedded `/cli/canvas` editor (and any deck route) is a
tool's editing UX, not the product identity (#95). Tool surfaces may exist inside Design
Studio; none of them may rebrand the loop, fork its state, or present itself as the system of
record.

### 11. Branch model

All M7 work branches `feat/*` off `develop` only (ADR-095). A1 ships as
`feat/m7-a1-design-loop-adr`; A2–A7 branch from `develop` after this ADR is Accepted.

## Alternatives considered

- **Canvas as the loop** (the loop lives in the Canvas product). Rejected: it makes one tool
  the execution authority, forks Goal/eval state into product-local stores, and repeats the
  drift DESIGN-STUDIO.md was written to prevent.
- **Client-side pipeline** (the browser orchestrates Explore/Execute/Evaluate). Rejected:
  evidence would not attach to canonical Runs, HITL fences would have no waiting NodeRun to
  decide on, and provenance (ADR-090226-9c3f style) would be unrecoverable.
- **Sidecar eval service** (`EvalRun` records in their own store/identity). Rejected: it is the
  second identity this contract forbids; eval evidence must be reconstructible from the Run
  lineage it belongs to.
- **Reuse Persona `RubricEval` as the Goal Rubric.** Rejected: different object (persona
  template quality vs. desired-outcome acceptance), different owner (`maistro.personas` vs.
  the Goal-acceptance facet), different lifecycle (no Goal/revision binding). Naming them the
  same would be the confusion, not a shortcut.
- **Let each domain lane (product/game/book) define its own loop nouns.** Rejected: that is
  exactly the second-product outcome; Packs specialize a shared loop precisely so the nouns do
  not fork.

## Consequences

- A2 (Rubric), A3 (loop Graph), A4 (eval-on-Run), A5 (fence), A6/A7 (packs, host integration)
  implement onto this kind table and cite it; a lane that needs a new kind or a new redirect
  target amends this ADR first.
- The shared ontology (`maistro.interop`) gains the `Rubric`/`CreativeBrief`/`Pack`/
  `FenceDecision` concepts and their canonical owners when their owning lanes land — as
  ontology extensions with exact identities, not as parallel registries. Until then, the
  kind-fencing contract test pins the reserved names and the single-Goal-identity invariant.
- `maistro.personas` keeps `RubricEval` unchanged (ADR-060); no M7 lane may rename, absorb, or
  re-point it at Goals.
- The convergence matrix keeps its one execution identity claim: the loop appears as Graphs and
  Runs, not as a new subsystem with its own lifecycle owner.
- This PR deliberately does **not** land Rubric persistence, eval wiring, packs, fence runtime,
  or any UI (stop condition, #790).

## Status and ratification

`Proposed` with an explicit merge-blocking status: this ADR and SPEC-092926-7a01 are the M7
gate. Dependent lanes (A2–A7) are `blocked-by` this decision; the commit that flips this ADR to
`Accepted` is the ratification event and must land on `develop` before any M7 runtime PR.

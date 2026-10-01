---
id: ADR-093026-7a90
title: "The design process is a first-class object graph — Rubric, eval-on-Run, packs, and the HITL fence live on the canonical pipeline"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-30
history:
  - status: Proposed
    date: 2026-09-30
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-032
  - maistro-engine#ADR-060
implements: []
related:
  - maistro-engine#SPEC-093026-7a90
  - maistro-engine#ADR-092626-c1e7
  - maistro-engine#ADR-091726-7c2a
  - maistro-engine#ADR-088
supersedes: []
blocks: []
blocked-by: []
contracts: []      # kinds declared here once #791-#796 land the marked tests (ADR-032 cross-check)
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-093026-7a90: The design process is a first-class object graph — Rubric, eval-on-Run, packs, and the HITL fence live on the canonical pipeline

## Context

Epic #789 (M7-A) asks for the design process itself to become a first-class
MAIstro object graph, proven once in this repo:

```
Workspace → Project → Goal
                      ↑ owned by Agent
                      ↓ scored by Rubric (versioned, first-class)
                      ↓ fulfilled by Graph (pack selects shape)
                      ↓ executed as Run / NodeRun / Attempt
                      ↓ evaluated on that same Run
                      ↓ fenced with park / redirect / accept
                      ↓ refined as a later Attempt, not a new universe
```

What exists today:

- The canonical semantic and execution chains are frozen in
  `docs/architecture/INTEROP-ONTOLOGY-v1.md` and the importable registry
  `maistro.interop.INTEROP_ONTOLOGY_V1`: `Workspace → Project → Goal` with
  `Agent → owns Goal`, and `Graph → Run → NodeRun → Attempt`. Goal's canonical
  owner is named as `maistro.goals`; that package is not implemented yet — the
  ontology explicitly allows naming a semantic owner before milestone behavior
  lands.
- The ontology layer (`maistro.ontology`, [ADR-036](ADR-036-ontology-semantic-object-layer.md))
  registers kinds with Pydantic semantic-facet models. No `rubric` kind exists.
- Evaluation exists only as output-level scorer providers
  (`maistro.protocols.scorer.Score`/`Scorer`, [ADR-060](ADR-060-persona-as-seed-and-eval-protocol.md))
  and the persona-authoring rubric in `maistro.personas.rubric`. Neither is
  bound to `Run`/`NodeRun`/`Attempt` records, and no versioned Rubric object is
  bound to a Goal.
- HITL exists as a pause: `human.ask_question` calls `pause_until` with
  `PAUSE_AWAITING_HUMAN_ANSWER`, the Run enters `RunStatus.WAITING`, and a
  completed node carries an `AcceptedNodeOutcome`. There are no park /
  redirect / accept fence semantics on waiting NodeRuns.
- M3 (#773) still treats success criteria as CreativeBrief fields and
  evaluation as project-quality critique (#779). M4 (#21) governs promotion of
  *system* artifacts and must not become the in-Run critic.
- Design Studio is a product surface (hive-conductor `/design-studio`), and
  #990 already contract-forbids a second design product.

Without a recorded contract, the first implementation of #791–#796 could grow
a Design-Studio-private Goal, Rubric, Run, eval, fence, pack registry, or demo
app — each a second universe contradicting the one-canonical-identity rule of
the interop ontology and the M1 convergence freeze.

## Decision (proposed)

The design process is not a new universe. Its objects are canonical objects on
the existing pipeline, and every M7 seam extends one shared surface:

1. **Rubric is a first-class ontology object bound to Goal.** A Rubric is
   registered as a `maistro.ontology` kind with a versioned semantic payload.
   A Goal binds exactly one Rubric version at a time; the binding records
   `rubric_id` + `rubric_version` and historical evidence stays recoverable
   against the version that scored it. The persona-authoring rubric and ADR-060
   scorer providers keep their roles; neither becomes the Goal-bound Rubric.
2. **Eval scores land on the same Run/NodeRun/Attempt.** An eval record names
   the `run_id`/`node_run_id`/`attempt_id` that produced the artifact and the
   `rubric_id`/`rubric_version` it scored against. Evaluation never writes a
   parallel truth: Run success/failure remains evidence and never silently
   completes a Goal (interop ontology rule 5). There is no second eval store.
3. **Domain packs select shape; they are not identities.** Product, game, and
   book packs are interchangeable selectors over the same
   `Goal → Graph → Run` pipeline at the pack boundary. A pack adds no identity,
   lifecycle, ownership, or private registry. Canvas, Deck, Builders, and later
   media are backends reached through `Capability → Provider → Binding →
   Invocation` — never pack identities and never product identities (extending
   the #990 contract).
4. **park / redirect / accept is a HITL fence on waiting NodeRuns.** The fence
   operates on a NodeRun in `RunStatus.WAITING`: **park** holds the node with a
   recorded reason and resume path; **redirect** discards the waiting attempt's
   continuation and refines as a **later Attempt of the same NodeRun/Run**;
   **accept** records the waiting outcome as accepted evidence. The fence adds
   no lifecycle beside Goal and Run and no second scheduler.
5. **Refine is lineage, not a new universe.** A refinement is a later Attempt
   in the same Run/NodeRun lineage, scored against a Rubric version, so a
   reviewer can walk goal revision → Rubric version → scored attempt →
   refined attempt. Later Goal revisions never rewrite historical evidence.
6. **Evolve/RSI is a consumer of the same eval, never a second loop.** Evolve
   (experimental, [ADR-088](ADR-088-maistro-evolve-experimental.md)) and RSI
   read the eval records the Run produced; they are forbidden from being the
   in-Run critic or from running a competing refinement loop. This mirrors the
   campaign boundary in [ADR-092626-c1e7](ADR-092626-c1e7-workspace-work-campaigns-are-narrowing-policy.md):
   the consumer consumes; it does not become authority.
7. **Design Studio is the host surface and carries the one public proof.** The
   proof (#795) ships in Design Studio against canonical records: pick one
   Goal, see its Rubric, watch a pack Run, read eval records on that Run,
   park/redirect/accept at a fence, and point at the refine Attempt's lineage.

**Stop condition (from the epic, restated as contract):** no Design-Studio-
private Goal, Rubric, Run, eval, fence, pack registry, or demo app. The
extension points are `maistro.ontology`, `maistro.runs`, `maistro.projects`
and the Goal owner `maistro.goals` it names, HITL NodeRuns, and Design Studio.

## Interface (proposed)

No code ships with this ADR. The children fix the exact signatures; the
contract pins only their homes:

- Rubric kind + versioned payload: `maistro.ontology` (registered kind).
- Goal ↔ Rubric binding: the canonical Goal owner (`maistro.goals` per the
  interop registry; `goal_id` + `goal_revision`).
- Eval records and fence transitions: `maistro.runs` (keyed by `run_id`,
  `node_run_id`, `attempt_id`; fence preconditions on `RunStatus.WAITING`).
- Pack manifest/selection: shared pack surface, not a product-private one.
- Proof surface: hive-conductor Design Studio routes over canonical records.

## Acceptance criteria

Layered contracts per [ADR-032](ADR-032-contracts-as-acceptance-criteria.md);
stable AC ids live in [SPEC-093026-7a90](../specs/SPEC-093026-7a90-closed-loop-design-process-contract.md):

- **Boundary contracts** (Pydantic): Rubric semantic payload; Goal↔Rubric
  binding; eval record keyed by run/node_run/attempt + rubric version; fence
  transition record.
- **Behavioral contracts** (unit + property): binding is single-version and
  recoverable; eval names the Run that produced the artifact; eval never
  mutates Goal terminal truth; redirect refines via a later Attempt; fence
  transitions only from `WAITING`; packs are interchangeable at the boundary;
  Evolve/RSI can read but not write in-Run eval; exactly one loop exists.
- **Cross-service contracts**: Design Studio reads only canonical records for
  the proof path; no private projection becomes authoritative.

## Test plan

| Test | Type | Covers |
|---|---|---|
| (child PRs add these; ids reserved in SPEC-093026-7a90) | boundary / behavioral / cross-service | AC-1 … AC-10 |

## Dependencies

- [ADR-036](ADR-036-ontology-semantic-object-layer.md) (ontology kind registry) must hold; Rubric rides it.
- [ADR-060](ADR-060-persona-as-seed-and-eval-protocol.md) scorer providers remain pluggable eval backends under the Run-bound record.
- The interop ontology (M1 freeze) is the identity authority; `maistro.goals` is named there and may land with #791.

## Out of scope

- Implementing the seams: #791 (Rubric ontology), #792 (eval-on-Run),
  #793 (packs), #794 (fence), #795 (proof), #796 (Evolve/RSI map) own them.
- Making Evolve/RSI autonomous (#796 is a mapping/contract issue, not an RSI enable).
- M4 governed promotion of system artifacts (#21) — it may later *train on*
  M7 evidence but is never the in-Run critic.
- Deciding the open questions in the SPEC (storage home of eval records, fence
  permission model, pack manifest format); the ADR stays `Proposed` with the
  SPEC until they are.

## Source references

- Epic #789; children #790–#796; parent initiative #788; milestone #787.
- `packages/maistro-core/src/maistro/runs/model.py` (`RunStatus.WAITING`,
  `Attempt`, `AcceptedNodeOutcome`, `ExecutionLease`).
- `packages/maistro-core/src/maistro/graph/nodes/human_ask_question.py` (pause-based HITL).
- `packages/maistro-core/src/maistro/protocols/scorer.py` (ADR-060 `Score`/`Scorer`).
- `packages/maistro-core/src/maistro/ontology/registry.py` (kind registration).
- `packages/maistro-core/src/maistro/interop/contract.py` (canonical concepts).
- `packages/maistro-core/tests/fitness/test_no_second_design_product.py` (#990).

## Inspirations

None beyond the in-repo precedents cited above.

## Links

- Contract spec: [SPEC-093026-7a90](../specs/SPEC-093026-7a90-closed-loop-design-process-contract.md)
- Related: [ADR-092626-c1e7](ADR-092626-c1e7-workspace-work-campaigns-are-narrowing-policy.md) (consumer-does-not-become-authority precedent)

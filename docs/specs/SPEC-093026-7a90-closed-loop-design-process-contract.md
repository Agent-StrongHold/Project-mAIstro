---
id: SPEC-093026-7a90
title: "Closed-loop design process — Rubric on Goal, eval-on-Run, packs, and the HITL fence"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-30
history:
  - status: Proposed
    date: 2026-09-30
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-032
  - maistro-engine#ADR-060
implements:
  - maistro-engine#ADR-093026-7a90
related:
  - maistro-engine#ADR-092626-c1e7
  - maistro-engine#SPEC-091726-7c2a
supersedes: []
blocks: []
blocked-by: []
contracts: []      # kinds declared here once #791-#796 land the marked tests (ADR-032 cross-check)
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-093026-7a90: Closed-loop design process — Rubric on Goal, eval-on-Run, packs, and the HITL fence

- **Status:** Proposed
- **Date:** 2026-09-30
- **ADR:** `ADR-093026-7a90` (Proposed)
- **Issue:** #790 (M7-A1). Parent epic #789; initiative #788; milestone #787.
- **Consumers:** #791 Rubric ontology, #792 eval-on-Run, #793 domain packs, #794 HITL fence, #795 public proof, #796 Evolve/RSI map
- **Technical Area:** ontology, runs, design-process runtime

## Context

Epic #789 makes the design process itself a first-class object graph and
proves it once in shipped Design Studio. The canonical chains already exist
(`docs/architecture/INTEROP-ONTOLOGY-v1.md`,
`maistro.interop.INTEROP_ONTOLOGY_V1`): `Workspace → Project → Goal` with
`Agent → owns Goal`, executed as `Graph → Run → NodeRun → Attempt`. What does
not exist: a Rubric as a registered ontology object, eval records bound to the
Run that produced the artifact, interchangeable domain packs, and park /
redirect / accept fence semantics on waiting NodeRuns. Today's eval is
output-level scorer providers (`maistro.protocols.scorer`, ADR-060) and M3's
project-quality critique (#779); today's HITL is a `human.ask_question` pause
into `RunStatus.WAITING`.

This spec records the contract and stable acceptance-criterion ids **before**
any code, so #791–#796's implementation PRs can mark proofs with
`@pytest.mark.ac`. It stays `Proposed` until the open questions below are
decided.

## Control flow

```
Workspace → Project → Goal
                      ↑ owned by Agent
                      ↓ bound to exactly one Rubric version at a time
                      ↓ fulfilled by Graph (pack selects shape: product | game | book)
                      ↓ executed as Run / NodeRun / Attempt
                      ↓ evaluated on that same Run (eval record names run/node_run/attempt)
                      ↓ fenced: park / redirect / accept on a WAITING NodeRun
                      ↓ refined as a later Attempt of the same lineage
                      ↓ read (never written) by Evolve/RSI
```

## Goals

- Make **Rubric** a first-class, versioned ontology object and bind it to Goal.
- Make **eval-on-Run** the only eval authority for a Goal's design loop.
- Make **packs** interchangeable shape selectors with no identity of their own.
- Make **park / redirect / accept** a fence on waiting NodeRuns that refines
  through later Attempts, never a second lifecycle.
- Give #795 one public proof path over canonical records, and #796 one read-only
  eval consumer contract.

## Non-goals

- **A Design-Studio-private universe.** No private Goal, Rubric, Run, eval,
  fence, pack registry, or demo app (epic stop condition).
- **A second scheduler or lifecycle.** The fence and eval add no authority
  beside Goal and Run; `ExecutionLease` / `StaleExecutionFence` semantics are
  unchanged.
- **Goal truth mutation.** Run success/failure stays evidence; eval records
  never complete a Goal (interop ontology rule 5).
- **An RSI enable.** #796 maps Evolve/RSI onto the same eval as a consumer and
  forbids a second loop; it does not turn RSI on (ADR-088 stays experimental).
- **M4 promotion.** Governed promotion of system artifacts (#21) may later
  train on M7 evidence but is never the in-Run critic.

## Decision

### Rubric (AC-1, AC-2)

A Rubric is a `maistro.ontology` registered kind whose semantic payload is
versioned; criteria live in the payload, and a bump creates a new version
rather than mutating history. A Goal binds at most one Rubric version at a
time; the binding records `rubric_id` + `rubric_version` so any historical
eval stays resolvable to the version that scored it. `maistro.personas.rubric`
and ADR-060 scorer providers keep their existing roles and are not promoted
into the Goal-bound Rubric.

### Eval-on-Run (AC-3, AC-4)

An eval record is keyed by the `run_id` / `node_run_id` / `attempt_id` that
produced the artifact and names the `rubric_id` + `rubric_version` it scored
against. Scores are records on the canonical execution objects; there is no
side eval store with independent authority. Eval records never write Goal
terminal truth.

### Packs (AC-5, AC-6)

Product, game, and book packs are interchangeable selectors of Graph shape at
the pack boundary: same Goal, same Run model, same fence, same eval. A pack
may not add identity, lifecycle, ownership, or a private registry. Canvas,
Deck, Builders, and later media are backends reached through
`Capability → Provider → Binding → Invocation` — never pack identities and
never product identities (extends the #990 no-second-design-product contract).

### HITL fence (AC-7)

`park`, `redirect`, and `accept` are fence transitions on a NodeRun in
`RunStatus.WAITING`:

| Action | Meaning | Record |
| --- | --- | --- |
| `park` | hold the node with a reason; a resume path stays open | attributed park record |
| `redirect` | discard the waiting continuation; refine as a **later Attempt** of the same NodeRun/Run | attributed redirect record + new Attempt |
| `accept` | record the waiting outcome as accepted evidence | `AcceptedNodeOutcome` semantics |

The fence is attributed and durable; it adds no lifecycle beside Goal and Run.

### Refine lineage (AC-8)

A refinement is a later Attempt in the same Run/NodeRun lineage. From a refine
Attempt a reviewer can reach the earlier scored Attempt, the Rubric version
that scored it, and the `goal_revision` in scope. Later Goal revisions never
rewrite historical evidence.

### Evolve/RSI consumer map (AC-9)

Evolve and RSI read the same eval records every other reader sees. They never
write in-Run eval records and never run a competing refinement loop: exactly
one loop exists, the Run's.

### Public proof (AC-10)

The #795 proof ships in Design Studio over canonical records only: pick one
Goal, see the Rubric version it is scored against, watch a pack Run, read eval
records on that Run, park/redirect/accept at a fence, and point at the refine
Attempt's lineage.

## Acceptance criteria

Each id is stable for `@pytest.mark.ac` marking by the child PR that proves it.

- **AC-1 (boundary):** `rubric` is a registered `maistro.ontology` kind whose
  semantic payload validates at `upsert`; version bumps create new versions;
  no second Rubric store exists.
- **AC-2 (behavioral):** a Goal binds at most one Rubric version at a time;
  the binding records `rubric_id` + `rubric_version`; historical eval remains
  resolvable to the version that scored it after a rebind.
- **AC-3 (boundary + behavioral):** an eval record names the
  `run_id`/`node_run_id`/`attempt_id` that produced the artifact and the
  `rubric_id`/`rubric_version` scored; eval records cannot be keyed to
  execution objects they did not score.
- **AC-4 (behavioral):** writing or updating eval records never mutates Goal
  terminal truth or Run/NodeRun/Attempt lifecycle state.
- **AC-5 (behavioral):** product, game, and book packs execute the same Goal
  through the same Run model and are interchangeable at the pack boundary; a
  pack introduces no identity, lifecycle, ownership, or private registry.
- **AC-6 (behavioral):** pack outputs reach Canvas/Deck/Builders only through
  `Capability → Provider → Binding → Invocation`; no pack or product identity
  is minted at that boundary (extends #990).
- **AC-7 (behavioral):** `park`/`redirect`/`accept` apply only to a NodeRun in
  `RunStatus.WAITING`; each transition is attributed and durable; `redirect`
  refines via a later Attempt of the same NodeRun/Run; `accept` records
  accepted evidence; no new lifecycle state is introduced.
- **AC-8 (behavioral):** refine lineage is recoverable: earlier scored Attempt
  → Rubric version → `goal_revision` → later Attempt; later Goal revisions do
  not rewrite historical evidence.
- **AC-9 (behavioral + cross-service):** Evolve/RSI can read eval records and
  cannot write them from inside a Run; exactly one refinement loop exists.
- **AC-10 (cross-service):** the shipped Design Studio proof path reads only
  canonical records (no private projection is authoritative) and exhibits:
  Goal → Rubric version → pack Run → eval records → fence action → refine
  lineage.

## Open questions (decided before this spec leaves Proposed)

- **Q1 — eval record home:** rows beside the runs tables in `maistro.runs`, or
  ontology entities under the Rubric kind? (Lean: `maistro.runs`; the record
  is execution evidence, and the interop registry already keys Run/NodeRun/
  Attempt there.)
- **Q2 — eval write authority:** which actors/providers may append eval
  records, and how a scorer provider's identity is attested on the record.
- **Q3 — fence permission model:** who may park/redirect/accept (Goal owner
  Agent vs. human Workspace actors), and how the fence interacts with
  `ExecutionLease` and the existing `human.ask_question` resume path.
- **Q4 — pack manifest format:** where a pack declares its Graph shape, and
  how pack selection is recorded on the Run for lineage.

## Dependencies

- [ADR-036](../adr/ADR-036-ontology-semantic-object-layer.md) kind registry (Rubric rides it).
- [ADR-060](../adr/ADR-060-persona-as-seed-and-eval-protocol.md) scorer providers stay pluggable eval backends under the Run-bound record.
- Interop ontology v1 is the identity authority; `maistro.goals` is named there and may land with #791.

## Out of scope

Implementing the seams (children #791–#796), enabling RSI autonomy, and M4
promotion semantics (see the ADR).

## Source references

Same evidence base as [ADR-093026-7a90](../adr/ADR-093026-7a90-design-process-is-a-first-class-object-graph.md):
`maistro.runs.model` (`RunStatus.WAITING`, `Attempt`, `AcceptedNodeOutcome`),
`maistro.graph.nodes.human_ask_question`, `maistro.protocols.scorer`,
`maistro.ontology.registry`, `maistro.interop.contract`, and the #990 fitness
contract.

## Links

- Decision ADR: [ADR-093026-7a90](../adr/ADR-093026-7a90-design-process-is-a-first-class-object-graph.md)
- Related: [SPEC-091726-7c2a](SPEC-091726-7c2a-brief-interview-before-goal-commit.md) (the interview that precedes Goal commit)

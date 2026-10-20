---
id: ADR-101726-e4bb
title: "Verification-aware execution and adaptive routing contracts"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-17
history:
  - status: Proposed
    date: 2026-10-17
substrate:
  - maistro-engine#ADR-097
implements: []
related:
  - maistro-engine#SPEC-177
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/graph/verification/test_taxonomy.py
  - packages/maistro-core/tests/graph/verification/test_expectations.py
  - packages/maistro-core/tests/graph/verification/test_escalation.py
  - packages/maistro-core/tests/graph/verification/test_routing.py
  - packages/maistro-core/tests/graph/verification/test_quality.py
  - packages/maistro-core/tests/graph/durable_runs/test_verification_supervision.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-101726-e4bb: Verification-aware execution and adaptive routing contracts

## Context

Epic #106 (M4-I) asks for execution quality supervision on the canonical
durable spine: predicted post-states checked against observed reality,
an actionable/transitional/terminal taxonomy for tool results, cheap-first
quality-triggered model escalation, and text-vs-image observation routing.
The epic text itself gates implementation on recording the contract first:
"Model choices, numerical thresholds and classification semantics are
unresolved until that contract is recorded."

The first landed slice (commit `8b7fd16cc`) shipped the primitives and the
executor integration; review of that slice found the contract was encoded in
code and tests but never recorded as an ADR, and that two of the four
primitives had no production wiring yet (no shipped node self-reported
quality, so the escalation gate had no live input; observation routing had
no production egress caller). This ADR records the contracts and the
production wiring decisions that close those gaps, so the next slice — and
any reviewer — can check the code against a written decision instead of
reverse-engineering one.

## Decision (proposed)

### 1. Predicted-versus-observed post-state

A node may declare its predicted post-state on the immutable Graph snapshot
as `policies["expect_post_state"]`:

```json
{
  "expect_result_state": "transitional",
  "expected_output": {"status": "deployed"},
  "expected_output_contains": {"summary": "shipped"},
  "description": "planner predicted deployment"
}
```

- `expected_output` asserts a **subset** of the node's output mapping by
  JSON equality (dotted paths address nested values). A subset, not the
  whole mapping: supervision exists to catch wrong worlds, not harmless
  extra fields.
- `expected_output_contains` asserts substrings on string output fields.
- `expect_result_state` asserts the classified result state (§2).
- The executor's authoritative fold supervises every completed frontier
  against the plan queue. A violation **halts the Run** with error code
  `PlanPostStateMismatch` and the verdict's `describe()` text as durable
  error evidence. The physical Attempt stays completed — the halt is
  logical, never a rewrite of evidence. Mismatch halts rather than pauses
  because nothing external owes an answer; resuming without new work would
  only re-read the same world.
- Graphs that declare no expectations execute exactly as before.

### 2. Result-state taxonomy and its mapping to lifecycle contracts

Every *successful* `NodeResult` classifies into exactly one state
(`maistro.graph.verification.taxonomy`):

- `ACTIONABLE` — the result hands the next move to an external actor.
- `TRANSITIONAL` — state moved forward; more in-graph work follows
  (the conservative default for a silent result).
- `TERMINAL` — the goal is satisfied; nothing is owed.

Failed results are deliberately outside the taxonomy: a failed result has
no post-state to classify, and `error_code`/`error_message` already say what
happened. Mapping to the existing contracts, not beside them:

- An explicit `result_state` metadata override wins; an unknown value raises
  (a typo in node code is a bug to surface, not a default to absorb).
- A pause whose `paused_reason` is in `HUMAN_PAUSE_REASONS`
  (`graph/nodes/base.py`'s one table) is ACTIONABLE — the pause table stays
  the single owner of "who owes the next action".
- `goal_satisfied` truthy metadata is TERMINAL; `requires_actor_action`
  truthy metadata is ACTIONABLE.

**Actor-requested delegation integration:** `agent.delegate_remote` is the
taxonomy's flagship consumer. Its pause is ACTIONABLE via the shared pause
table (`awaiting_remote_delegation` is answer-gated), and its terminal
outcomes self-declare through the new result-metadata channel (§4): a
delegation that ends `rejected`, `timed_out`, or `uncertain` writes
`result_state=actionable`, because the next move — re-delegate, escalate to
a person, give up — belongs to the delegating actor. `completed` declares
nothing (TRANSITIONAL default: in-graph work follows), and `failed` declares
nothing because the graph may branch on the status itself.

### 3. Cheap-first quality-triggered escalation

A node may declare a model ladder on the snapshot as
`policies["escalation_ladder"] = {"models": [cheapest...strongest],
"quality_floor": 0.0..1.0}`. The fold's supervision:

- reads the node's self-reported `quality` result metadata (§4);
- on a miss, **withholds** the visit from advancement and re-queues it as a
  **fresh NodeRun/Attempt** whose `NodeContext.metadata["escalated_model"]`
  names the next rung — never a rewritten Attempt;
- is bounded by the node's existing `max_attempts` visit budget and its
  replay-semantics contract: non-retryable nodes never escalate, and an
  exhausted ladder or budget accepts the shortfall as final while keeping
  the shortfall in the accepted visit's evidence. There is no unbounded
  retry or escalation loop by construction.
- Budget accounting stays with the canonical Invocation; each rung's
  completion is its own keyed effect
  (`llm.summarize.complete:<run>:<node>:<digest>`, where the digest covers the
  rung and the node's inputs), so escalation never replays an unbilled call
  under a reused key.

`llm.summarize` moves from `NON_RETRYABLE` to `EFFECT_KEY` replay semantics
under this contract. Nothing changes for graphs that declare neither
`max_attempts` nor a ladder (default budget is one visit); the change only
opens the door supervision walks through, and it is honest because the
governed completion already files its Invocation under a stable Run/node/input
scoped effect key — a re-visit is a new keyed effect, not a blind replay — and
the rung is part of that key's digest, so two nodes on one Binding and model
never share an effect.

### 4. Node self-reporting: the result-metadata channel

`NodeContext.result_metadata` is the one channel through which a node's
`_execute` self-reports facts *about its output* — `quality` for the
escalation gate, an explicit `result_state` for supervision. `BaseNode.run`
merges it into the successful `NodeResult.metadata` after `_execute`
returns; the executor-owned `replay_effect_key` merges last so a node cannot
spoof the reconciliation boundary. The context is per-visit, so a report
cannot leak across visits. Failure metadata keeps traveling on the raised
exception and pause metadata on `pause_until` — the channel is a report
about an output, never a second outcome path.

`llm.summarize` self-reports
`quality = maistro.graph.verification.quality.summarize_quality(source,
summary)` — a deterministic structural score (compression + salient-token
coverage, `0.5/0.5`), no judging model call. Deterministic on purpose: a
gate whose input moved between visits would escalate at random. Graphs that
declare no ladder carry the score as evidence only.

### 5. Observation modality routing at the model egress

`llm.summarize` accepts `observations` (upstream payloads), `text_model`
(default: the node's own `model`) and `image_model` inputs. Each observation
is classified text-or-image (`classify_observation`), routed to the alias
configured for its modality, and encoded into the content-part shape the
routed model accepts (`encode_observation`). Rules:

- An image observation with no `image_model` alias **refuses loudly**:
  feeding an image part to a text-only alias fails at the provider, and
  re-encoding it as text discards exactly what the observation carried.
- Text observations never change the model alias — they encode as text
  content parts.
- Precedence when both apply: a supervision-chosen rung (§3) outranks the
  modality floor, because the ladder is declared by the same graph author
  who knows the observations' modalities; otherwise an image observation
  lifts the request to the vision alias.
- Quality is measured against everything the model was shown as source (the
  text input plus the text half of the observations), so a summary cannot
  score well by ignoring the payloads it was handed.

## Consequences

- Supervision, escalation and routing are node policies on the immutable
  Graph snapshot, executed by the one authoritative fold. No second
  scheduler, retry loop, result-status authority, Goal store, or delegation
  mechanism is introduced; Goal -> Graph -> Run -> NodeRun -> Attempt
  remains the only lifecycle, and every escalation/delegation stays inside
  existing permissions, budgets and the canonical Invocation.
- A planted post-state mismatch is durably explained and stops the Run
  rather than continuing under assumed success; removing the supervision
  makes the focused behavioral tests fail.
- Transitional/unavailable/terminal results cannot conflate with a completed
  effect or trigger an unbounded loop: failed results have no state to
  classify, and escalation is bounded by ladder length, visit budget and
  replay semantics.
- The quality heuristic is a floor, not a verdict. Workloads that find it
  wrong simply declare no ladder; the score rides along as evidence.
- The comparison against fixed-routing baselines is recorded in
  [`docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json`](../benchmarks/m4i-adaptive-vs-fixed-baseline.json):
  the same workload runs through this ADR's production path (real
  `llm.summarize`, governed egress, supervision fold) under an adaptive arm
  and three fixed single-alias arms, against a deterministic model-dependent
  stub gateway — offline and reproducible via
  `scripts/bench_m4i_adaptive_vs_fixed.py`, asserted in
  `tests/graph/verification/test_adaptive_vs_fixed_baseline.py`. On that
  workload the adaptive arm matches the strongest fixed baseline's task
  success at lower cost and modeled latency, escalated tasks honestly pay
  double (their cheap visit was already billed), and every fixed alias
  records the failure cases adaptivity avoids (shipped shortfalls; refused
  image tasks). The stub's numbers are workload- and rate-dependent, not a
  universal claim; live-provider telemetry would land beside them, not
  replace the contract.

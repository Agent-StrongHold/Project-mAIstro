---
id: SPEC-070226-3bbd
title: "Evolve reflect — TextGrad-style node attribution for multi-node DAG pipelines"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-02
substrate:
  - maistro-engine#ADR-088
  - maistro-engine#SPEC-207
  - maistro-engine#ADR-062
implements: []
related:
  - maistro-engine#SPEC-062926-8ec5
  - maistro-engine#SPEC-070226-83bd
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-3bbd: Evolve Reflect — TextGrad-Style Node Attribution

## Context

`reflect.py`'s `extract_signal()` always targets the **entry node** of the
pipeline genome for prompt optimization (SPEC-207 §1: "Target node = entry node,
because benchmarks execute the entry node's prompt"). This is correct for
single-node pipelines and for benchmarks that exercise only the entry node. It is
wrong for multi-node `PipelineGenome` DAGs where the failure can originate in a
downstream node whose prompt the entry node's optimization cannot reach.

TextGrad (Yuksekgonul et al., 2024) propagates "textual gradients" — LLM-
generated natural-language explanations of *why* a downstream step failed and
*what* an upstream step should do differently — backward through a multi-step
pipeline. The result is node-level attribution: you optimize the node that is
actually responsible for the failure, not always the entry node.

Adapting TextGrad's core idea natively (without the TextGrad library, per the
no-external-optimizer-dependency posture of ADR-088 and SPEC-207):

- A benchmark failure trace already contains enough information to ask an LLM
  "which pipeline stage produced this error?"
- The answer can be used to select the target node for mutation, replacing the
  hardcoded entry-node assumption in `extract_signal()`.

## Goals

- Replace the hardcoded entry-node target in `extract_signal()` with an
  LLM-driven attribution step that names the most likely responsible node given
  the failure trace.
- Gracefully degrade to the entry-node default when attribution is unavailable
  (no LLM, single-node pipeline, no failure traces).
- Preserve all acceptance, stub-guard, budget, and margin-floor invariants.

## Non-goals

- Implementing the full TextGrad library or its automatic differentiation
  machinery.
- Optimizing multiple nodes simultaneously in one reflection cycle.
- Changing the mutation operator applied to the attributed node — `mutate_prompt()`
  is unchanged; only the *target* node selection changes.

## Decision

1. **Attribution prompt.** New function `_attribute_failure_to_node(genome,
   failure_traces, llm_call) -> str | None`. Builds a prompt containing the
   pipeline's node list (id + role), the failure traces from the weakest
   benchmark, and asks the LLM to name the node id most responsible. Returns
   `None` if the LLM response doesn't match any node id in the genome (parse
   failure → fall back to entry node).

2. **`extract_signal()` update.** After identifying the weakest benchmark (current
   logic unchanged), calls `_attribute_failure_to_node()` when failure traces are
   present and `llm_call` is not None. Uses the attributed node id as
   `target_node_id`; falls back to the entry node id when attribution returns
   `None` or is skipped (stub guard, no traces).

3. **Challenger spawn.** `spawn_challenger()` already accepts a `target_node_id`
   parameter path — the deep-copy sets the target node's prompt field when
   constructing the challenger. This is the surface this spec wires into.

4. **Config.** `EvolutionConfig.node_attribution` (bool, default `True`): opt-out
   flag to disable the attribution LLM call and always use the entry node. Allows
   cost-sensitive runs to skip the extra LLM call.

## Acceptance criteria

- For a multi-node genome whose failure traces name a downstream node, the
  attributed target node differs from the entry node and the challenger's prompt
  change targets the attributed node.
- When attribution returns an unrecognised node id, the entry node is used and
  no error is raised.
- With `node_attribution=False` or a single-node pipeline, attribution is
  skipped and the entry node is used (no extra LLM call).
- All pre-existing `test_reflect.py` tests continue passing unmodified.

## Testing

New unit tests in `packages/maistro-evolve/tests/test_reflect.py`:
`test_attribution_targets_downstream_node_from_traces`,
`test_attribution_falls_back_on_unrecognised_response`,
`test_attribution_skipped_when_disabled`,
`test_attribution_skipped_for_single_node_genome`.
Fake LLM callables are used (no network); unseeded-randomness rule applies.

## Open questions

- Should node attribution consume one of the `self_improve_candidates` budget
  slots (since it's an extra LLM call), or should it be a zero-cost step charged
  separately? Proposing a separate charge (attribution call is not a proposal
  call) to keep the candidates budget semantically clean.
- Once SPEC-202's real-fidelity adapters land and per-node execution traces are
  available from benchmarks like swebench, should attribution be replaced by
  deterministic trace-based node selection? Attribution LLM call would then only
  run as fallback when traces are sparse.

## References

- Yuksekgonul et al., "TextGrad: Automatic Differentiation via Text" (2024) —
  textual gradient propagation through multi-step LLM pipelines; node-level
  attribution as the key mechanism.
- maistro-engine#SPEC-207 — defines `extract_signal()`, `spawn_challenger()`,
  and the failure-trace contract this spec extends.
- maistro-engine#ADR-062 — DAG execution protocol; defines the node model
  (`PipelineNode`, entry node concept) this spec operates on.
- maistro-engine#SPEC-062926-8ec5 — edit budget and margin floor; acceptance
  invariants inherited unchanged.
- Implementation surfaces: `packages/maistro-evolve/src/maistro_evolve/reflect.py`,
  `types.py` (`EvolutionConfig`, `PipelineGenome`).

---
inventory-delta:
  packages/maistro-core/tests: +58
---

# M4-I verification-aware executor and adaptive routing evidence

Implements the first landed slice of epic #106 (verification-aware executor
and adaptive routing) on the canonical durable spine:

- `maistro/graph/verification/` adds the four M4-I primitives:
  `taxonomy` (actionable/transitional/terminal classification of successful
  results, with failed results deliberately outside the taxonomy),
  `expectations` (the plan queue: per-node predicted post-states declared in
  `policies["expect_post_state"]`, deterministic topological consumption),
  `escalation` (cheap-first quality-triggered model ladders declared in
  `policies["escalation_ladder"]`), and `routing` (text-vs-image observation
  modality routing and model-aware content-part encoding).
- `durable_runs/authoritative_fold.py` supervises completed frontiers
  against the plan queue and halts the Run with `PlanPostStateMismatch`
  when reality contradicts the plan (mirroring the existing blackboard-halt
  stop contract), and withholds quality-short visits to re-queue them at
  the next ladder rung — a fresh NodeRun/Attempt within the node's existing
  `max_attempts` visit budget and replay-semantics contract, never a
  rewritten Attempt.
- `durable_runs/executor.py::_build_ctx` surfaces the supervised escalation
  decision to re-visits as `NodeContext.metadata["escalated_model"]`;
  `llm.summarize` honors it for its model call.
- 49 unit tests cover the four primitives
  (`packages/maistro-core/tests/graph/verification/`); 9 durable
  integration tests cover halt-on-mismatch, escalation within budget,
  ladder exhaustion, and the non-retryable refusal
  (`test_verification_supervision.py`).

Net: +58 collected node IDs on `packages/maistro-core/tests`.

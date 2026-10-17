---
inventory-delta:
  packages/maistro-core/tests: +81
---

# M4-I verification-aware executor and adaptive routing evidence

Implements epic #106 (verification-aware executor and adaptive routing) on
the canonical durable spine, in two slices.

**Slice 1 — the four M4-I primitives and executor supervision:**

- `maistro/graph/verification/`: result-state taxonomy (actionable /
  transitional / terminal; failed results have no post-state to classify),
  plan-queue post-state expectations declared in
  `policies["expect_post_state"]`, cheap-first quality-triggered escalation
  ladders declared in `policies["escalation_ladder"]`, and text-vs-image
  observation modality routing + model-aware content-part encoding.
- `durable_runs/authoritative_fold.py` supervises completed frontiers
  against the plan queue and halts the Run with `PlanPostStateMismatch`
  when reality contradicts the plan (same visible-stop contract as the
  blackboard halt); withholds quality-short visits and re-queues them at the
  next ladder rung as a fresh NodeRun/Attempt within the node's existing
  `max_attempts` visit budget and replay-semantics contract.
- `durable_runs/executor.py::_build_ctx` surfaces the supervised escalation
  decision to re-visits as `NodeContext.metadata["escalated_model"]`.

**Slice 2 — production wiring for the two gated primitives (review repair):**

- `graph/nodes/base.py`: `NodeContext.result_metadata` is the production
  self-report channel; `BaseNode.run` merges it into the successful
  NodeResult (executor-owned `replay_effect_key` last, so it cannot be
  spoofed from a node's report).
- `graph/verification/quality.py`: `summarize_quality`, the deterministic
  compression+coverage score that feeds the escalation gate.
- `llm.summarize` self-reports `quality` on every completion, accepts
  `observations` with modality routing (`text_model`/`image_model`; an
  image without a vision alias refuses loudly instead of re-encoding as
  text), and moves to `EFFECT_KEY` replay semantics so a declared ladder
  can actually escalate (default visit budget is still one).
- `agent.delegate_remote` self-declares `result_state=actionable` for the
  actor-owed terminal outcomes (rejected / timed_out / uncertain), beside
  the pause path that is already ACTIONABLE through `HUMAN_PAUSE_REASONS`.
- `docs/adr/ADR-101726-e4bb` records the node-policy contracts
  (`expect_post_state`, `escalation_ladder`, result-state mapping,
  self-report channel, observation routing precedence).

Tests: 49 unit tests for the four primitives + 9 for the quality heuristic
(`packages/maistro-core/tests/graph/verification/`); 10 durable integration
tests for halt-on-mismatch, escalation within budget, ladder exhaustion,
the non-retryable refusal, and the production self-report channel
(`test_verification_supervision.py`); 7 `llm.summarize` egress tests
(`test_llm_summarize_verification.py`); 6 delegation result-state tests
(`test_agent_delegate_remote_verification.py`).

Net: +81 collected node IDs on `packages/maistro-core/tests`.

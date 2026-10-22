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

## CI-repair round (develop sync + gate evidence)

No inventory delta moves in this round: the repair touches one existing
assertion set in `packages/hive-conductor/backend/tests` (an edited test, not a
new node), so every `inventory-delta` block above still holds.

- **develop sync.** The branch was behind: `e20e9f52` was not an ancestor of
  head. `origin/develop` is merged in (merge commit `c4045b3d6`) with six
  conflicts resolved in place — `durable_runs/executor.py` (kept the extracted
  `_supervision_context` helper, which owns develop's inlined
  resumed-pause-carry block verbatim), `nodes/base.py` (kept the M4-I
  `result_metadata` channel), `nodes/agent_delegate_remote.py` (kept the
  `verification.taxonomy` import the ACTIONABLE self-report uses),
  `docs/adr/ADR-INDEX.md` (kept this epic's ADR row), and both ledgers
  (`quality/radon-baseline.json` drops develop's `_build_ctx` row — the
  extraction leaves it at `B (8)`, below the ratchet; `quality/vulture-baseline.json`
  takes develop's two-space file rather than the branch's accidental
  nine-space re-indent).
- **Vulture honesty fix.** `llm_summarize._effective_rung`'s local named
  `escalated` shadowed `RepairCycleResult.escalated`, which is why vulture
  could not see that property is genuinely unused. Renamed to
  `escalation_rung`; the banked row for `capabilities/slots/self_repair.py:70`
  is now truthful and stays.
- **Hive e2e repair (the `test` job's real, branch-caused failure).**
  `test_e2e_authenticated_real_model_graph.py` still asserted the retired
  model-only effect key `llm.summarize.complete:{model}`, which this epic
  replaced with the Run/node/input-scoped key precisely so two `llm.summarize`
  nodes on one Binding cannot adopt each other's completed summary. The three
  reads now ask the node for its key (`node.logical_effect_key(...)`) and
  assert it is Run/node scoped and *not* the model-only spelling.
  Load-bearing: restoring a model-only derivation in
  `_scoped_effect_key` fails `test_canonical_llm_node_crosses_the_governed_invocation_seam`.
- **ADR truth.** `ADR-101726-e4bb` §3 spelled the per-rung key
  `llm.summarize.complete:{rung}`; it now states the shipped derivation
  (`<run>:<node>:<digest>`, digest covering the rung and the inputs) so the
  ADR and the code name the same key.

Gate evidence for this round (CI-exact args, worktree `/home/dev/Git/wt/auto-106`):
ruff check/format clean; `check-suite-inventory.py` ok (21 suites, 32484 node
IDs); `check-test-duplicates.py` ok; vulture/radon gates exit 0; diff-coverage
gate ok (13 measured files ≥90% lines / ≥80% branches) from a full
`packages/maistro-core/tests` run under `--branch --source=…/maistro` plus the
bench test under `--source=scripts`; suites green — core 15737 passed, server
571, turing 887, ext 420, hive backend 3768.

**Inherited, not ours, and still red:**
`maistro.runs.admission_identity` (landed on develop by #1851, commit
`c8c8adbff`/PR #1936) has no production importer, so `check-reachability.py`
reports it NEWLY UNREACHABLE and three root-suite self-checks fail
(`tests/test_reachability_baseline_identity.py` ×2, `tests/test_check_reachability.py`).
Proven on a pristine `git archive` export of `origin/develop` at `e20e9f52`:
the same one finding, with `quality/reachability-baseline.json` and
`quality/ratchet-authorizations.json` untouched by that PR. Its own notes
record the exit as owner-held ("a develop-side reviewed grant landed before
this stack"). Adding the baseline row here cannot clear it — `load_authorizations`
reads `quality/ratchet-authorizations.json` from the merge base only — so this
branch leaves both reachability ledgers at a zero-line diff rather than land an
unauthorized row. (Refs #106, #1851)

---
inventory-delta:
  packages/maistro-core/tests: +42
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 794-design-fence

Issue #794 (M7-A5): park / redirect / accept become HITL decisions on the
canonical waiting NodeRun (#48, #737), per ADR-092926-7a01 §8 — the
`FenceDecision` kind whose canonical owner is `maistro.runs`. The suite grows
`tests/graph/durable_runs/test_fence_decisions.py`; no existing test module
was weakened.

What the tests pin, mapped to the issue's acceptance list (delta arithmetic:
32 tests in the new fence module — 19 fence-decision scenarios plus 13
fail-closed refusal/edge tests (decision-model refusals, composition
refusals, the Goal-lineage stand-in's own rules, the multi-fence frontier,
the malformed-binding refusal, and the generic-answer re-arm) — + 1
idempotency test in `tests/projects/test_rubric_store.py` + 3
`test_node_composition.py` cases that parametrize over every registered node
kind and therefore grew by the `human.fence_decision` registration + 1
`test_human_pause_reasons.py` case parametrized over `EXPECTED_HUMAN`, which
now names `awaiting_human_decision`):

- **Durable fence wait (#737 invariant).** A loop Graph with the real
  `human.fence_decision` gate at a pack-declared `evaluate.accept` fence
  point pauses as a PAUSED Run with a `kind: "hitl"` pause entry that names
  the fence point and the Goal/Rubric revisions being consumed; a fresh store
  instance over the same SQLite file (process restart) restores the identical
  waiting NodeRun and pause entry, and a decision after the restart resumes
  the same Run to COMPLETED. The new pause reason
  `awaiting_human_decision` is classified in both `PAUSE_REASON_OWNERS`
  (human) and `PAUSE_RESUME_CONDITIONS` (answer-gated), so the structural
  pause tables and the executor cannot disagree about the fence.
- **Park preserves everything.** Park writes only the decision record: status
  stays PAUSED on the same waiting NodeRun, the Goal/Rubric binding, the
  persisted deadline (`park` neither extends it nor defuses the expiry tick),
  and the Run's eval records are byte-identical; an accept afterwards resumes
  the same Run. The composition layer exposes all three verbs symmetrically —
  `park_fence` routes the hold through the same canonical store rules the
  store-level tests pin, records the decision under the authorization's
  principal, and leaves the fence answerable by a later decision.
- **Redirect is target-explicit and history-preserving.** Redirect-goal mints
  Goal revision N+1 through a Goal-lineage port that is the *same* authority
  the Rubric store resolves liveness through (#458 seam — no second Goal
  store), re-binds the Rubric as revision N+1 against the new Goal revision,
  and bumps the brief version; prior eval scores still name the old Goal and
  Rubric revisions, and the decision record names what the Run consumed *at
  decision time*. Redirect-rubric mints a Rubric revision bound to the same
  Goal revision. Redirect-brief bumps only `brief_version` and provably mints
  no Rubric revision. The decision model rejects a redirect that names
  revisions its target does not imply (no mixed blobs).
- **Accept is evidence-derived and grants nothing.** `accept_fence` derives
  `gate_passed`/failing dimensions from the Run's persisted eval records
  (M7-A3 `eval_summary`) — a Run with failing *or missing* dimensions cannot
  be accepted without a recorded non-empty rationale, and the rationale is
  enforced by the decision model itself at the durable store boundary. The
  accept decision record carries no capability/grant/authority fields and the
  Run's provenance gains none.
- **Cancel ≠ park.** From identical fences, cancel terminalizes (CANCELLED,
  refuses further decisions) while park keeps the Run waiting and still
  accepts a later decision.
- **No UI-only pause.** Park is refused on a COMPLETED Run, on a `kind: "wait"`
  system pause, and on a HITL-paused Run that lacks the loop binding in its
  provenance; every refusal leaves the durable record untouched. The canonical
  backend mirrors fence settlements onto the spine Run (PAUSED → QUEUED →
  COMPLETED) without a second lifecycle, and a resume payload that is not a
  recorded fence decision (a plain answer) re-arms the same waiting NodeRun
  instead of being read as a verdict.

Repair-round additions (this note's delta grew from 24 to 37): the redirect
binding now lives in the durable graph state (`loop_binding`, written by
`redirect_record`, read by `fence_binding`) because the canonical store
re-projects `record.run` from the spine — whose launch provenance stays as
admitted (#1572) — so a provenance-only rewrite silently reverted on the
canonical backend; the spine-parity test now drives park → brief-redirect
→ resume through `CanonicalDurableRunStore` and pins the durable binding
against the untouched spine provenance. The composition layer gained
`park_fence` (the hold verb's entry, making the three verbs symmetric and
the module reachable through the package facade — it had no src import edge
and read as new unreachable debt). The `human.fence_decision` node extracts
its pause-answer lookup so the class sits under the complexity ceiling, and
malformed metadata now fails closed pending instead of crashing.

Later repair rounds (delta 37 → 42; five tests in `test_fence_decisions.py`
that earlier rounds landed without recording: the bound-revision accept
test, the pre-mint redirect-refusal test, and three from this round):

- Redirect authorizes and validates *before* minting — `redirect_fence`
  runs `require_hitl_authorization`, a non-consuming Workspace `permits`
  check, and the new `require_answerable_fence` before `_plan_redirect`
  publishes any Goal/Rubric revision, so a denied caller, an elapsed
  deadline, or a node that is not the waiting fence can no longer move
  canonical state it could never bind (the durable write re-checks both
  under its own lock and consumes the evidence there). A rubric-only
  redirect pins `update_dimensions` to *this Run's* Goal revision instead of
  inheriting the Rubric's latest binding, which a concurrent redirect on a
  shared Rubric could have moved.
- The plain answer path is no longer a fence door. `submit_hitl_answer`
  previously consumed the fence pause for *any* answer and the node re-armed
  on resume — which also let a caller-supplied `{"decision": "accept",
  "gate_passed": true}` ride the verbatim-copy answer writer into the
  readable answer slot. `answer_record` now persists such submissions for
  audit without consuming the pause (the malformed-verdict rule, extended to
  the fence node), and the node additionally reads a verdict only from an
  answer the settlement methods stamped `fence_decision: True`. Tests pin
  the store refusal, the forged-payload refusal through the #737 expiry
  tick, and the node's stamp rule at its own seam; the earlier
  "plain answer re-arms the fence" wording above described the pre-fix
  behavior and is superseded by this one.
- The accept rationale rule keys on the gate result itself: a store-level
  `accept_hitl(gate_passed=False)` with the default empty
  `failing_dimensions` is still an override and refuses without recorded
  rationale, and a citation naming failing dimensions while asserting the
  gate passed is refused as contradictory evidence. `accept_fence`'s derived
  summary already satisfies both (a failed or missing dimension is exactly
  a non-passing gate), so no composition-path behavior changed.

Salvage note: while this suite was being written, an uncommitted foreign edit
to `maistro/projects/rubric_store.py` (+ its test) appeared in the worktree,
syntactically broken mid-application ("idempotent create retry preserves
created_at"). It was preserved and completed (orphaned duplicate fragment
removed; `quality/` baselines untouched), and its own new test passes in
`tests/projects/test_rubric_store.py` — counted in that suite's inventory,
not here.

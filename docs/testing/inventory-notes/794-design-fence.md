---
inventory-delta:
  packages/maistro-core/tests: +23
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 794-design-fence

Issue #794 (M7-A5): park / redirect / accept become HITL decisions on the
canonical waiting NodeRun (#48, #737), per ADR-092926-7a01 §8 — the
`FenceDecision` kind whose canonical owner is `maistro.runs`. The suite grows
`tests/graph/durable_runs/test_fence_decisions.py`; no existing test module
was weakened.

What the tests pin, mapped to the issue's acceptance list (delta arithmetic:
18 tests in the new fence module + 1 idempotency test in
`tests/projects/test_rubric_store.py` + 3 `test_node_composition.py` cases
that parametrize over every registered node kind and therefore grew by the
`human.fence_decision` registration + 1 `test_human_pause_reasons.py` case
parametrized over `EXPECTED_HUMAN`, which now names
`awaiting_human_decision`):

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
  the same Run.
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
  COMPLETED) without a second lifecycle.

Salvage note: while this suite was being written, an uncommitted foreign edit
to `maistro/projects/rubric_store.py` (+ its test) appeared in the worktree,
syntactically broken mid-application ("idempotent create retry preserves
created_at"). It was preserved and completed (orphaned duplicate fragment
removed; `quality/` baselines untouched), and its own new test passes in
`tests/projects/test_rubric_store.py` — counted in that suite's inventory,
not here.

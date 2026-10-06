---
inventory-delta:
  packages/maistro-core/tests: +80
---
# 960-external-agent-lifecycle-normalization

Remote Agent lifecycle normalization (M9-D3, epic #941) lands as
`packages/maistro-core/src/maistro/a2a/normalize.py` — exported through
`maistro.a2a` — and rewires the `agent.delegate_remote` resume path so a
remote protocol status never settles a child Run on its own word.

**+53 `packages/maistro-core/tests/a2a/test_normalize.py`** — one test (or
parametrized matrix) per rule, each naming the #960 acceptance criterion it
pins:

- *closed projection* (17-case + 6-case matrices + 1): the A2A task states
  and their common synonyms project onto `RemoteState` — the delegation's
  own classified outcome ladder (`DelegationStatus`: completed, failed,
  rejected, timed_out) plus two orthogonal facts (`progress`, `cancelled`),
  never a second state ladder of our own (`REJECTED` keeps its own outcome
  because declined work never ran, unlike a mid-flight cancellation);
  unmapped values — including near-misses like `completed-with-errors` —
  are unknown, never proximity-matched into a completion.
- *settlement decisions* (10): only recognized terminal states settle; a
  remote `completed` for an already-terminal child is refused with the
  canonical status named (the core "remote `completed` cannot override
  canonical Run terminal truth" rule); recognized progress never settles; a
  remote cancellation settles failed with the fact named; an unmapped status
  fails loudly on an open child and is refused on a terminal one.
- *retry governance* (9): completed/cancelled/rejected are `FORBIDDEN`
  (the remote outcome owns the retry decision); explicit post-acceptance
  failure/timeout is `EFFECT_KEY_GOVERNED` (only the canonical effect-key
  reservation may admit more work, never a fresh transport submission);
  ambiguous and in-flight states are `RECONCILE_ONLY`, and the reason reports
  which side of the transport boundary the caller believes it is on.
- *cancellation truth* (3 + 1 composition): the projection is `cancelled`
  with or without a remote acknowledgement, and the composition case pins that
  a cancelled-without-ack child still refuses a late remote `completed`.
- *progress records* (5): sequence numbering, reconnect re-report flagged
  `duplicate` instead of counted as new progress, new-state-not-duplicate, and
  the history cap.

**+16 `packages/maistro-core/tests/a2a/test_external_agent_conformance.py`**
— the conformance suite against an external-style Agent implementation: a
stateful A2A-protocol peer with its own vocabulary, wire protocol (idempotent
`POST /a2a/tasks/create`, `GET /a2a/tasks/by-idempotency-key/{key}`
reconciliation, a pollable task-status resource) and a poll-driven lifecycle
engine, served over real httpx transport semantics. Cases: vocabulary
conformance (every state the peer can emit is mapped; a state the peer grows
fails the suite until MAIstro maps it); progress→completion across reconnects
settling one child / one NodeRun / exactly two Attempts; remote `completed`
after local cancellation refused end to end through
`RunExecutionService.cancel_run`; a lost response recovered through the peer's
reconciliation endpoint with `creates == 1` (no second submission); explicit
remote failure classified `EFFECT_KEY_GOVERNED`; and the peer's idempotent
admission never minting a second task for a presented key.

**+11
`packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_normalization.py`**
— the node-side behaviors the pure normalizer tests cannot pin: recognized
progress answers re-park the `awaiting_remote_delegation` pause without
minting a NodeRun or Attempt; progress history rides the pause metadata across
reconnects with duplicate re-reports flagged; progress cannot extend the
delegation deadline (expiry settles `timed_out` with the last remote state
named); store-less transport construction still re-parks; synonym completion,
remote cancellation (failed + reason), remote rejection (child cancelled), and
a `timed-out` synonym setting the `timed_out` flag; and a late duplicate
answer for a completed child refused with the original result intact.

Fail-before evidence: muting `decide_settlement`'s canonical-terminal branch
makes `test_remote_completed_cannot_override_canonical_terminal_truth` and
`test_a_late_answer_for_a_completed_child_is_refused_not_settled` fail (the
remote outcome would ride through); reverting the progress re-park makes every
progress test settle the child falsely instead of parking. Both mutations were
applied and reverted on this head (2026-10-06); the canonical-terminal
mutation was re-run after the RemoteState repair and failed exactly those two
tests before being reverted again.

Validation on this head (895657fb + the normalization repair below):
`pytest packages/maistro-core/tests` 12909 passed / 938 skipped / 1 xfailed
(a2a + graph/nodes slices: 269 passed); the CI-exact `mypy --strict
packages/maistro-core/src` is clean (after `uv sync --locked --all-extras`,
matching CI's install); `ruff check`/`format --check` clean tree-wide;
`check-reachability.py` unchanged (1288 modules / 170 unreachable);
`check-suite-inventory.py` ok (15 suites match the recorded inventory).

Per-identity gates over the files this change touches, run with CI's exact
arguments:

- `uv run python scripts/check-execution-lifecycles.py` — OK: 19 work-state
  vocabularies, all classified. The draft's original `RemoteLifecycleState`
  StrEnum was a NEW work-state vocabulary with no already-landed grant at the
  merge base (the two-merge rule bars the candidate from authorizing its own
  addition), so the projection was rewritten to decompose onto the
  already-classified `agent_delegate_remote::DelegationStatus` ladder plus
  orthogonal `progress`/`cancelled` facts; the candidate
  `quality/execution-lifecycles.json` row for the removed identity was pruned
  with it.
- `uv run python scripts/check-radon-baseline.py` — OK: 138 C-or-worse
  blocks, 0 new/regressed/stale. `_resume` was refactored from D(21) into
  `_resume_pause_identity` / `_child_run` + `_canonical_truth` /
  `_late_answer_failure` / `_settled_output`, each below the baseline
  threshold, so no complexity grant is needed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — OK: 1341 findings, all
  banked, 0 new. The one stale ledger row
  (`capabilities/invocation.py::unused variable 'observed_at'`) is debt this
  branch's own code eliminated (the scan-wide name is now used by
  `normalize.py`'s progress observation), so the row was pruned from
  `quality/vulture-baseline.json`; the scan introduces no new identities.

## Develop-sync merge (this round, 2026-10-06)

`origin/develop` (56332162c, the M4-B/#958/#1990 convergence) was merged into
the branch; the only conflict was `maistro/a2a/__init__.py`, where develop's
#958 discovery exports and this change's #960 normalization exports are
disjoint — resolved as the alphabetical union of both `__all__` lists (the
import block had merged cleanly). Verified bidirectionally that every `__all__`
name is imported and vice versa; `from maistro.a2a import ...` resolves for
both vocabularies.

Re-validation on the merged head b752c6462: `pytest
packages/maistro-core/tests` 13068 passed / 938 skipped / 1 xfailed (a2a +
graph/nodes slice: 250 passed); the three per-identity gates re-run with CI's
exact arguments all exit 0 — execution-lifecycles 19/19 classified, radon
138/138 with 0 new/regressed, vulture 1335 findings all banked with 0
unclassified; `mypy --strict packages/maistro-core/src` clean (730 files,
after `uv sync --locked --all-extras` matching CI's install); `ruff check` /
`format --check` clean tree-wide; `check-suite-inventory.py --suite
packages/maistro-core/tests` ok (14007 node IDs, 0 duplicate identities);
`check-reachability.py` ok (1295 modules / 170 unreachable); `check-shipped-
surface-truth.py` ok. Upstream CI on the pre-merge head remains unverified
(check-runs captured queued/None); nothing in this round mutates GitHub.

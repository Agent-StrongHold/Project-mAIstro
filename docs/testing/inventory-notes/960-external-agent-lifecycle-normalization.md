---
inventory-delta:
  packages/maistro-core/tests: +80
---
# 960-external-agent-lifecycle-normalization

Remote Agent lifecycle normalization (M9-D3, epic #941) lands as
`packages/maistro-core/src/maistro/maistro.a2a.normalize` — exported through
`maistro.a2a` — and rewires the `agent.delegate_remote` resume path so a
remote protocol status never settles a child Run on its own word.

**+53 `packages/maistro-core/tests/a2a/test_normalize.py`** — one test (or
parametrized matrix) per rule, each naming the #960 acceptance criterion it
pins:

- *closed projection vocabulary* (9-case + 6-case matrices + 1): the A2A task
  states and their common synonyms normalize onto the eight-plus-one member
  set (`REJECTED` is its own member because declined work never ran, unlike a
  mid-flight cancellation); unmapped values — including near-misses like
  `completed-with-errors` — are `UNKNOWN`, never proximity-matched into a
  completion.
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
makes `test_remote_completed_cannot_override_canonical_terminal_truth` and the
node-level late-answer refusal fail (the remote outcome would ride through);
reverting the progress re-park makes every progress test settle the child
falsely instead of parking. Both mutations were reverted before commit.

Validation on this head: `pytest packages/maistro-core/tests` 12907 passed /
940 skipped (665 in `tests/a2a` + `tests/graph/nodes`); the CI-exact mypy
invocation over all six package src trees is clean; `ruff check`/`format
--check` clean tree-wide; `check-reachability.py` unchanged (1288 modules /
170 unreachable); the CI-exact vulture scan produces zero new identities
(a pre-existing stale ledger row for
`capabilities/invocation.py::observed_at` fails identically on the pristine
base c560d4cca and is left for the ledger lane).

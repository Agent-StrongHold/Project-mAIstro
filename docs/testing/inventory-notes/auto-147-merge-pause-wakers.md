---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147 merge repair: `awaiting_remote_delegation` joins the #1192 waker map

## The conflict the merge left

`1e1f78f48` merged develop's `750edd84d` (#1192: "every parked Graph pause
reason names a reachable production waker") into this branch. Both parents
touch the same seam and the merge took each side's file whole:

- **base.py took the auto-147 side.** `PAUSE_REASON_OWNERS` classifies
  `awaiting_remote_delegation` as `"human"` — answer-gated, parked PAUSED —
  which is #147's accepted design: the delegating node pauses carrying the
  child Run id and is resumed through the same durable answer seam as every
  other externally answered node (`test_human_pause_reasons.py` records the
  decision; `answer_record` in `graph/durable_runs/stores.py` carries a
  comment naming `agent.delegate_remote` as the reason the pause stamping
  exists).
- **test_pause_reason_wakers.py took the develop side**, which encodes the
  pre-#147 world: the reason owned by `"system"`, parked WAITING, and
  ledgered in `UNWOKEN` as a known gap because nothing delivered an answer to
  it. On develop that was true *because* of the bug #147 fixes — the delegate
  node was unreachable-by-default and nothing could wake its pause.

Three architecture tests failed at the merged head, each asserting the
develop-half of the split against a tree that ships the auto-147 half:
`test_parked_status_follows_the_executor`, 
`test_the_hitl_answer_path_cannot_wake_a_waiting_delegation`, and
`test_every_mixed_human_frontier_is_released` (the last indirectly: a
PAUSED-parking reason with no waker entry breaks the mixed-frontier
release check).

## The repair, and why it strengthens #1192 rather than weakening it

The ledger's own contract says "removing an entry is how #1192 closes". The
gap #1192 recorded for `awaiting_remote_delegation` is closed on this branch:
production now delivers an answer to the delegation pause. So the repair maps
the reason to the same `_HUMAN_WAKERS` every other answer-gated reason uses
and removes the ledger entry. The architecture test goes from *excusing* the
delegation pause to *proving* it: reachable `answer_human_work` route,
canonical `submit_hitl_answer` API, accepted parked status (PAUSED), and a
drain for the QUEUED Run the answer leaves behind.

- `PAUSE_REASON_WAKERS` gains
  `PAUSE_AWAITING_REMOTE_DELEGATION: _HUMAN_WAKERS`; `UNWOKEN` keeps only
  `awaiting_harness` (still the open gap).
- `test_parked_status_follows_the_executor` now pins both halves of the
  owner split: the delegation parks PAUSED, its timer-resumable
  reconciliation sibling parks WAITING.
- `test_the_hitl_answer_path_cannot_wake_a_waiting_pause` keeps the negative
  property on a reason that still parks WAITING and system-owned
  (`awaiting_delegation_reconciliation`): the answer path refuses it on both
  the parked status and the owner.
- `test_a_reason_without_a_waker_or_ledger_entry_fails` re-points its fixture
  at `awaiting_harness` for the same reason.
- New positive pin `test_the_answer_path_delivers_a_paused_delegations_answer`:
  `answer_record` accepts a PAUSED `agent.delegate_remote` Run, queues it for
  its drain, and hands the resuming node the child Run id stamped from the
  pause the node itself wrote — the exact seam
  `test_agent_delegate_remote_review.py` exercises end to end.

## Validation

`uv run pytest packages/maistro-core/tests/graph/durable_runs/test_pause_reason_wakers.py`
34 passed (was 3 failed / 30 passed); full `packages/maistro-core/tests` green
after the change; `check-suite-inventory.py` records the net +1.

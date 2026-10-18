---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-147 CI gate repair

Repairs the three CI failures recorded at head `d6b1b6b697591d63099c2e715ac412406023b81b`
(exact-debt-ledger, Quality gate, Coverage gate). Two collected nodes are added
to `packages/maistro-core/tests/agents/test_factory.py`, covering the two
changed branch arcs the diff-coverage floor rejected (75% of 8 arcs, need 80%):

- `test_delegator_without_registration_surface_is_refused` — a configured
  delegator whose `register_agent_capability` is not callable is a loud
  `ConfigError` at roster construction (`factory.py:318` raise arc), not a
  silently unprojected allow-list.
- `test_empty_roster_registers_no_direct_submission_principal` — with an empty
  roster the reserved `DIRECT_SUBMISSION_AGENT` principal stays unregistered
  (`factory.py:325` false arc), so a direct admission naming any target is a
  real refusal.

The other two CI failures are not test-count changes:

- vulture exact-debt-ledger: pruned the stale row
  `a2a/delegate.py::unused method 'register_agent_capability'` from
  `quality/vulture-baseline.json`. The #147 factory wiring references the
  method via `getattr`, which vulture counts as a use, so the recorded debt no
  longer exists; the gate requires fixed debt to be pruned ("Fixed debt must be
  pruned from the candidate ledger"). This is mandatory candidate bookkeeping,
  not a new debt or grant authorization.
- radon Quality gate: `_record_child_outcome` (C, 16) and
  `_dispatch_cross_instance` (C, 12) in
  `graph/nodes/agent_delegate_remote.py` were split into rank-B helpers
  (`_open_child_node_runs`, `_record_node_run_attempt`, `_cancel_child`,
  `_settle_peer_submission`) — behavior-preserving extraction, no grant
  landed: the file now has zero C-or-worse blocks and the ratchet reads
  70 -> 70.

---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# Inventory note — #1036/#2466 Conductor cancel-route mutation gate

Six node IDs added to `packages/hive-conductor/backend/tests` (all in
`test_dag_run_cancel_route.py`); no test removed or renamed.

- `test_same_workspace_peer_can_read_but_not_cancel_another_initiator_s_run` —
  the #2466 P0 negative: a same-Workspace peer may GET the initiator's Run but
  its cancel is the seam's one 404, with no Run/NodeRun/Attempt write and no
  physical provider stop.
- `test_workspace_administrator_can_cancel_a_run_the_initiator_started` — the
  positive half of the same gate: a Workspace administrator who did not
  initiate may cancel, and the physical work still stops.
- `test_cross_workspace_projection_link_cannot_delegate_cancellation` — a
  projection row filed in Workspace X linked to a live canonical Run in Y
  gives an X-only caller no mutation authority over Y.
- `test_cross_workspace_link_refuses_even_an_admin_of_the_run_s_workspace` —
  the projection-to-Run association is enforced even for a principal who
  administrates the Run's own Workspace through the cross-linked row; the same
  principal still cancels by the canonical id.
- `test_cancel_by_direct_canonical_id_matches_the_projection_route` — direct
  canonical and valid projection IDs behave identically for the initiator.
- `test_cancel_refusal_is_indistinguishable_across_foreign_and_unknown_ids` —
  foreign principal, forged canonical link, and absent id all answer the
  identical non-disclosing 404.

Red-before evidence: the three negative tests failed against the pre-gate
route at head `33ac30c5f1` (peer cancel returned 200 and terminalized the
Run; cross-Workspace rows delegated mutation). Green-after: the route resolves
the canonical target through `RunStoreBoundary.require_run_mutation` (the
shared maistro-server owner/administrator rule, no parallel Conductor policy)
and refuses mismatched projection links before any cancellation work.

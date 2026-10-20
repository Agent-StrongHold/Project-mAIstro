---
inventory-delta:
  packages/maistro-core/tests: +2
---

# Issue 42 — preserve canonical delegation recovery across develop sync

Salvaged the supplied unfinished merge of ce19fd99e into auto-42. Conflict markers
in `a2a/guest_peers.py` prevented production imports and all driver validation.
Retain incoming caller/Goal/scope admission and authenticated, idempotent transport;
retain the branch's guard against memoizing a dispatch with no receipt.

Executed conformance then exposed a semantic merge failure: the incoming remote
node passed the removed `logical_effect=True` keyword to canonical Invocation
services. Use the delegation's stable replay key as `effect_scope` for dispatch,
completed-result lookup, and reconciliation. Do not resurrect an opt-in identity
contract or alternate authority. Two direct-node tests expected replay metadata
no longer authored by BaseNode; assert against the canonical replay-key function
instead of changing production metadata ownership to satisfy those fixtures.

Meaningful regression coverage (+2 collected cases):

- Add empty-dispatch-receipt recovery test: real GuestPeerManager + HTTP mock must
  GET the peer's receipt, then cache the actual receipt (one POST, one GET).
- Parameterize crashed RUNNING Invocation recovery across same/new NodeRun. A new
  manager (no receipt cache) recovers through GET, never re-POSTs, settles the
  original Invocation, and preserves its original NodeRun/Attempt correlation.

ADRs 1f7c/a66b/f383/b36a remain authoritative: persist Attempt before Runtime;
Runtime identity is Attempt ID, stores own lease/fence authority. b36a extends
f383 with liveness-based reclaim; no competing execution or authorization path.

The remaining develop merge (a8258ee24) conflicted only in the inventory
baseline: retain the branch's compacted counts/folded notes and add develop's
new SDK suite at zero, whose incoming notes supply its count. This is conflict
reconciliation, not a count ratchet. Executed inventory gates agree: core
14,336; server 525; canvas 519; design 573; extension SDK 118. The focused
A2A/delegation/extensions suite passes 635 tests. Exact vulture scan passes
1,332 reviewed identities, zero unclassified; no ledger edits are justified.

Fault injection outside the tree proved both regressions: caching an empty
receipt fails the recovered task-ID assertion; dropping the stable effect scope
leaves the original Invocation RUNNING and creates a second row on fresh-NodeRun
recovery. Without injection, all three new/parameterized cases pass.

Validation and final gate outcomes are recorded in
`docs/issue-42-repair-387420.md` for job 387420793df94683812cb2ceefa0deb5. Incoming merge tests/notes for #956/#959
are preserved, not counted again by this +2 delta.

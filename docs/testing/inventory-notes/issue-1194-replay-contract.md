---
inventory-delta:
  packages/maistro-core/tests: +14
  packages/maistro-server/tests: +1
---
# issue-1194-replay-contract

The branch's net contribution to the suite ledger is +14 core and +1 server
node IDs. They add evidence for the executable Graph replay contract:

- the non-retryable contract overrides a larger graph retry budget;
- an EFFECT_KEY node without a recorded key is not retried by the graph executor;
- `compliance.block` repeated execution upserts one penalty by its logical effect key;
- `dashboard.append_section` repeated execution leaves one section;
- repeated, independent-worker, and concurrent `agent.delegate_remote` execution reuses one child Run and one in-process A2A task;
- the SQLite canonical store retains one effect claim across a store reload, and one transport-claim winner across replicas;
- a harness effect is deduplicated across a new NodeRun, not only a new Attempt;
- a registry-wide idempotency conformance suite (`test_idempotent_replay_conformance.py`) executes every IDEMPOTENT-declared kind twice against the same logical input/state — durable state upserts to one effect, poll replays stay read-only — and the sweep test fails when an IDEMPOTENT declaration has no conformance case;
- the server test proves repeated inbound A2A admission returns one canonical Run.

The catalog assertion also verifies replay semantics (`idempotent` included) are
emitted from the executable node contract, never a second hand-written table.

## suite-ledger reconciliation (recorded for review)

The note first shipped with a malformed front matter — the opening `---`
delimiter was missing — so the gate read no delta from it at all, and the
branch's two develop merges moved collection underneath it. The numbers above
are the gate's own `--update` result for this branch's net contribution after
that repair: they are whatever makes baseline + Σ(notes) match collection, per
the ledger's convention for a change whose base moved.

## develop-merge reconciliation (recorded for review)

The branch merged develop `ba2f1f077` (which had independently fixed delegation
double-dispatch in #1270 "admit child run before transport"). Reconciliation
decisions, all in favour of one canonical contract:

- `agent.delegate_remote` keeps #1270's reserve-before-transport architecture
  (child reservation, atomic transport-claim, receipt attach, reconciliation
  pauses), but its delegation key is bound to the canonical
  `replay_effect_key` (Run + node + input digest) instead of a NodeRun-scoped
  hash — a NodeRun-scoped key was this issue's finding: a retry that gets a
  new NodeRun defeats dedup. The child Run's provenance records the same value
  under both `delegation_key` (transport lookup) and `effect_key` (executor
  reconciliation lookup).
- The guest-peer POST body carries `idempotency_key` (the canonical
  `A2ATaskCreate` receiver contract) and the server gained
  `GET /a2a/tasks/by-idempotency-key/{key}` so `GuestPeerManager.reconcile`
  has an in-tree receiver; it resolves the claim through
  `RunStore.find_run_by_effect`.
- One review test pinned "adopt the reservation even when the payload changed
  after a crash". That contradicts the canonical contract (`replay_effect_key`:
  the input digest distinguishes explicit new work at the same node) and is
  unreachable in production, where a retry re-reads the NodeRun's durable
  inputs. The test now pins both halves of the canonical semantics: same
  durable inputs adopt the reservation (same child, same task, transport
  accepted once); a genuinely different request is explicit new work.
- The effect-claim migration was renumbered `034` → `041` (develop's chain
  claimed 034/039/040 while this branch was open); per the convention in
  `036_audit_log_org_scope`, the audit-scope migration follows the new tip so
  `upgrade head` stays single-headed and applies it.

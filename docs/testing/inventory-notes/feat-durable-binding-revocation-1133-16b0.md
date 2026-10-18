---
inventory-delta:
  packages/maistro-core/tests: +6
---
# feat-durable-binding-revocation-1133-16b0

Six additions to `packages/maistro-core/tests/capabilities/test_binding_invocation.py`;
nothing removed, renamed or reparameterised, so the net and the gross agree.

Five cover durable revocation, which did not exist. `InMemoryBindingStore`
could withdraw a Binding "permanently for this store's lifetime" — the two
durable backends could not withdraw one at all — so a restart re-granted
every revoked capability and an operator who cut off a compromised Binding
and bounced the process had cut off nothing.

- **survives reopening the database** — the property the whole change is
  for. Fails against every prior revision, because no prior revision had a
  `revoke` on a durable store to call.
- **a revoked identity cannot be registered again** — the tombstone is the
  point. Deleting the row alone lets an actor that still remembers the id
  re-create it, which is the #846 failure.
- **revoking an unknown or already-revoked id is not an error** — revocation
  is a desired end state, not a transition. Raising would make the safe
  action look failed and invite a retry loop around it.
- **revoked denies distinguishably from unknown** — both raise
  `BindingNotFound`, but an operator reading "no registered definition" for
  a Binding they deliberately withdrew cannot tell whether it took effect.
- **PostgreSQL revocation holds for every replica** — the in-memory store's
  revocation is process-local, which on a replicated deployment means a
  capability cut off on one worker stays live on the others.

The sixth pins the protocol gap itself: every store carries `revoke`, and
`register` is *not* a `RevocableBindingStore` member. That asymmetry is the
substance of the change — `register` was declared synchronous, so no durable
store could ever satisfy the contract, while no effect path called it. Its
absence is load-bearing and a future edit restoring it would re-break every
durable effect context, so it is asserted rather than remembered.

The PostgreSQL fake in this file also had to learn the second table: it
answered every `fetchval` from its bindings map, so once the store read
revocations it reported each binding as revoked, the payload being truthy.
It routes on table name now. No test count changed from that.

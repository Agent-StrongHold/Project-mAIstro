---
inventory-delta:
  packages/maistro-core/tests: +10
---
# M2 Sentinel audit signatures

Adds coverage that in-memory Sentinel audit decisions carry an Ed25519 proof,
that mutation invalidates the proof, and that a different signing key cannot
verify a decision. Durable-store coverage pins the restart contract: a deny
decision carrying violations verifies after a durable round-trip (SQLite
integration; PG reconstructed from its INSERT params), and tampering a
persisted field invalidates the proof. Canonical decision bytes cover only the
fields durable stores serialize — the violations tuple and write-side
timestamp are storage metadata, never persisted by the shipped stores.

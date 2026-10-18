---
inventory-delta:
  packages/maistro-core/tests: +11
---
# M2 Sentinel audit signatures

Adds coverage that in-memory Sentinel audit decisions carry an Ed25519 proof,
that mutation invalidates the proof, and that a different signing key cannot
verify a decision. Durable-store coverage pins the restart contract: a deny
decision carrying violations verifies after a durable round-trip (SQLite
integration; PG reconstructed from its INSERT params), and tampering a
persisted field invalidates the proof. Canonical decision bytes cover only the
fields durable stores serialize — the violations
tuple, the write-side timestamp, and the correlation/route metadata (#1139
callers such as the user-model promotion auditor set action/run_id/
project_id/workspace_id on the same wired store) are storage metadata, never
persisted by the shipped stores; signing them would leave legitimate records
failing verify() after a restart.

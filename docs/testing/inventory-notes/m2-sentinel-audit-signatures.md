---
inventory-delta:
  packages/maistro-core/tests/security/sentinel/test_audit.py: +2
---
# M2 Sentinel audit signatures

Adds coverage that in-memory Sentinel audit decisions carry an Ed25519 proof,
that mutation invalidates the proof, and that a different signing key cannot
verify a decision.

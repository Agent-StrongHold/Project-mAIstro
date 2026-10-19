---
inventory-delta:
  packages/maistro-core/tests: +26
---
# M2 Sentinel audit signatures

Adds coverage that in-memory Sentinel audit decisions carry an Ed25519 proof,
that mutation invalidates the proof, and that a different signing key cannot
verify a decision. Durable-store coverage pins the restart contract: a deny
decision carrying violations verifies after a durable round-trip (SQLite
integration; PG reconstructed from its INSERT params), and tampering a
persisted field invalidates the proof. It also covers the ADR-073 surface
additions: `verify()` is admitted to the audit stores' append-only surface by
its own scoped case (a proof check that adds, removes, and rewrites nothing),
and a durable store whose signing key is process-generated warns at
construction naming `MAISTRO_AUDIT_SIGNING_KEY`.

Canonical decision bytes cover exactly the decision fields every shipped store
retains (boundary, principals, tool, verdict, detail, trace/request ids). The
violations tuple and the correlation/route metadata (#1139 callers such as the
user-model promotion auditor set action/run_id/project_id/workspace_id on the
same wired store) are never persisted by any shipped store, and the write-side
timestamp is ordering metadata — SQLite keeps it in its `timestamp` column and
PostgreSQL persists no decision timestamp at all. None of those fields are in
the canonical bytes: signing a field a stored row cannot reproduce would leave
legitimate records — deny decisions, the rows that most need tamper evidence —
failing verify() after a restart. The tradeoff is explicit: retimestamping or
reordering persisted rows sits outside the proof's coverage (ordering
metadata, not decision content), while tampering any persisted decision field
still invalidates it.

This change also executes the audit-log wiring contract service-free:
`_wire_audit_log` prefers PostgreSQL when both relational backends are
configured, runs the idempotent proof-column `ensure_schema` upgrade on the
selected backend (PG statements asserted on a fake pool; SQLite columns
asserted on a real in-memory database), and falls back to an in-memory log
that still signs every retained decision. On the signing seam itself it pins
canonical-byte behavior the durable stores rely on: non-dataclass entries are
rejected, a legacy empty verdict reads as `allowed` (identical canonical
bytes and signature), rich value shapes (datetime, tuple, nested dataclass,
dict) canonicalize deterministically with proof fields excluded at every
nesting depth, mutable entries are signed in place preserving identity, and
verify() rejects a wrong `proof_type` or a missing signature — not only
tampered decision bytes.

---
inventory-delta:
  packages/maistro-core/tests: +42
---

Coverage for tamper-evident Sentinel decisions (issue #69, ADR-073). The delta
is the whole change: the nine node IDs that previously sat unrecorded are the
parametrized per-field tamper cases, and the rest were missing from the ledger
when the lane's test count moved.

`tests/security/sentinel/test_integrity.py` (new, 37 node IDs) signs real
Ed25519 decisions and checks the contract the signature actually commits to:

- one case per protected field (`timestamp`, `boundary`, the five identity
  fields, `action`, `tool_name`, `verdict`, `detail`, `policy_snapshot`,
  `payload`, `inputs_hash`, `violations`) asserting verification fails — 15
  parametrized IDs, and a companion case that derives the signed field set from
  `canonical_decision_payload` so a field added to the contract without a tamper
  case fails loudly instead of going untested;
- verification modes as separate guarantees: embedded material detects in-place
  corruption, and a pinned verification-key reference (the ADR-073 "trusted
  credential") is what rejects a writer who swaps the public key and re-signs;
  disagreement between the row and the pinned reference fails closed;
- forged signatures (bit-flipped and non-base64), unsupported algorithm,
  unknown key, and unsigned records each resolve to a distinct
  `IntegrityStatus`, so unverifiable history is labeled `UNSIGNED` rather than
  reported as tampered or presented as signed;
- rotation: retired keys stay verifiable, retired *private* material is dropped
  at rotation, and the published keyring is public-only;
- product path: `Sentinel.authorize` for both an allowed and a denied
  principal, and `Sentinel.pre_call`, asserting the decision and the record
  agree, that `integrity` is returned to the caller, and that `pre_call` binds
  `inputs_hash` so a record cannot be replayed against different arguments;
- two subprocess cases that keep `cryptography` out of the type-module import
  graph (see `security/integrity_types.py`) while still failing loudly if the
  signer itself is used without the backend;
- SQLite durable round-trips for both verdicts, persist→reload→verify→alter
  each field→require failure, plus an unsigned historical row.

`tests/persistence/test_pg_audit.py` (+5 node IDs) covers the PostgreSQL
store's side: the signed timestamp is bound rather than left to the column's
`now()` default (a row that did could never re-verify), `inputs_hash` and the
public verification material are written and rebuilt on read, a signed decision
is re-verified from a row reconstructed from the emitted INSERT's own column
list, and an unsigned history row reloads with no verification material.

Verified against a live `pgvector/pgvector:pg18` database separately: the full
001→036 chain, `036` down/up reversible, and allowed plus denied decisions
written by `Sentinel` itself, reloaded, verified in both modes, and rejected
after each protected-field mutation.

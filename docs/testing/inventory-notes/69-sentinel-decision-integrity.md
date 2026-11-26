---
inventory-delta:
  packages/maistro-core/tests: +61
---

Coverage for tamper-evident Sentinel decisions (issue #69, ADR-073). The delta
is the whole change: the nine node IDs that previously sat unrecorded are the
parametrized per-field tamper cases, and the rest were missing from the ledger
when the lane's test count moved.

`tests/security/sentinel/test_integrity.py` (new, 41 node IDs) signs real
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
- the ADR-037 `policy.decision` event carries the same decision, `inputs_hash`
  and public verification material as the signed record, on both the
  authorization and `pre_call` gate paths;
- `DecisionSigner.from_seed_b64` reproduces the same key id/public key across
  process instances, rejects malformed or wrong-length material without
  echoing it, and the resulting record verifies against a pinned keyring;
- SQLite durable round-trips for both verdicts, persist→reload→verify→alter
  each field→require failure, plus an unsigned historical row.

`tests/test_container_wiring.py` (+3 node IDs) covers the product composition
root: `create_container` attaches the existing durable event log, a Sentinel
authorization reaches the `policy.decision` topic with the signed record's
public material, the same `MAISTRO_SENTINEL_SIGNING_KEY` seed yields the same
key reference across container instances, and a malformed seed fails startup
instead of silently falling back to an ephemeral key.

`tests/persistence/test_pg_audit.py` (+5 node IDs) covers the PostgreSQL
store's side: the signed timestamp is bound rather than left to the column's
`now()` default (a row that did could never re-verify), `inputs_hash` and the
public verification material are written and rebuilt on read, a signed decision
is re-verified from a row reconstructed from the emitted INSERT's own column
list, and an unsigned history row reloads with no verification material.

## Develop merge repair (2026-11-26)

The original verification claim for migration 036 is historical, not evidence
for this repair. Develop now owns migrations through 063; this lane appends
064 and retains the pre-existing store proof in `signature`, separately from
`decision_signature`. The frozen canonical AuditEntry replaces the former
mutable twin. New tests (+9 node IDs) cover:

- reinstalling the active signing key without deleting it;
- depth/cyclic/non-JSON arguments refused without audit hashing defeating the
  existing resource limit (3 IDs); rejected arguments have no available digest;
- missing key reference, public key or signature fails pinned verification (3 IDs);
- live PostgreSQL allowed/denied decisions, both proofs, every protected-field
  mutation, and secret non-retention;
- real SQLite file-backed container restart, both tool-call verdicts, scoped
  audit reads and canonical event correlation, using independently pinned keys.

Existing SQLite metadata and PG INSERT/schema assertions now reflect the retained
action and separate proofs; no test cases were removed. The seed validation
case also rejects a correctly sized seed with invalid base64 trailing bytes.

Repair validation results are recorded in `repair-69-handoff.md`.

## Revalidation (2026-11-26, post-merge head a3d5bb0a03)

The two items the repair handoff left pending are now discharged, and the
undcommitted `entity_id or ""` guard on the `policy.decision` event append is
confirmed load-bearing: with the HEAD variant (`entry.action or entry.tool_name`),
`uv run mypy` fails on `policy.py:710` — `Argument "entity_id" to "append" of
"EventLogStore" has incompatible type "str | None"; expected "str"` — because
`AuditEntry.tool_name` is `str | None`. With the guard the whole AGENTS.md
mypy battery passes (908 source files).

- Live PostgreSQL (pgvector/pg18 `maistro-pg-test` at 127.0.0.1:5433, private
  database `auto69_job_5f6f` dropped and recreated): `alembic upgrade head`
  runs 001→064 as a single linear chain ending at this lane's
  `064_sentinel_decision_integrity` — accurate at that head; the develop sync
  that followed made the numbering collide (see round 2). With `MAISTRO_TEST_PG_DSN` set,
  `test_pg_audit.py` + `test_integrity.py` give 73 passed / 0 skipped,
  including `test_real_pg_decisions_preserve_both_proofs_and_reject_all_mutations`
  (real allowed+denied `Sentinel.authorize`, reload, pinned-keyring VERIFIED,
  every `PROTECTED_FIELDS` mutation rejected, secret non-retention asserted
  against the raw PG rows) and
  `test_real_postgres_two_org_scope_and_schema`.
- Radon re-run after the merge checkpoint (the other pending item):
  `scripts/check-radon-baseline.py` green — 134 reviewed C-or-worse blocks
  match the scan.
- Full battery unchanged: targeted pytest (security + persistence audit +
  container wiring) 1540 passed / 28 skipped; ruff check and format clean;
  suite-inventory, security-inventory, doc-links, wiring-reads,
  contract-markers, backlog-consistency, vulture-baseline, reachability and
  promotion-surface gates all green. No test cases were added or removed this
  round, so the recorded delta stays +58.

## Repair round 2 (2026-11-26, head b3b94e5e51 + this commit)

The previous round's two claims did not survive re-verification against the
post-merge tree; both were real defects and were repaired in source (no
quality-ledger edits; `quality/` still matches origin/develop exactly):

- **Vulture ratchet red against the trusted base.** The CI invocation
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) failed with two NEW identities — the test-only
  `DecisionSigner.verification_history` and `Sentinel.verification_keyring`
  properties — and one recorded identity no longer found:
  `types/security.py::repair_action` was flipped to "used" by the envelope's
  `getattr(violation, "repair_action", ...)` read (vulture counts getattr
  strings as uses). Repaired without banking anything: the signed violations
  envelope now serializes via `dataclasses.asdict`, which covers every
  Violation field (including future ones) without naming `repair_action`, so
  the ledger row stays valid while the field stays inside the signature —
  canonical bytes are unchanged (`sort_keys=True` orders the same key set).
  `DecisionSigner.keyring` now derives from `verification_history`, and
  `create_container` publishes the Sentinel verification-key reference set
  (ids only) at composition time — the out-of-band pinning record ADR-073's
  amendment describes. Both properties now have production callers; the gate
  passes with the ledger untouched.
- **Duplicate Alembic revision `064`.** The develop sync at b3b94e5e51 landed
  develop's `064_canonical_personas` … `070_evolve_domain_publications`, while
  this lane's migration still claimed revision `064` off `063` (written when
  develop ended at 063). `alembic heads` showed two heads and `upgrade head`
  was ambiguous. Renumbered to `071_sentinel_decision_integrity`
  (`down_revision = "070"`); `alembic history` is a single linear chain.

Re-validation evidence (all commands run fresh on this round's tree):

- Live PostgreSQL (pgvector/pg18 `maistro-pg-test` at 127.0.0.1:5433, private
  database `auto69_job_7e217c` dropped and recreated): `alembic upgrade head`
  runs 001→071 linearly; with `MAISTRO_TEST_PG_DSN` set, `test_pg_audit.py` +
  `test_integrity.py` give 79 passed / 0 skipped, including
  `test_real_pg_decisions_preserve_both_proofs_and_reject_all_mutations`
  (real allowed+denied `Sentinel.authorize`, reload, pinned-keyring VERIFIED,
  every protected-field mutation rejected, secret non-retention against raw
  PG rows) and `test_real_postgres_two_org_scope_and_schema`.
- Targeted battery (security + persistence audit + container wiring):
  1633 passed / 31 skipped (unchanged counts; no cases added or removed, so
  the recorded delta stays +58).
- `ruff check .` and `ruff format --check .` clean; full AGENTS.md mypy
  battery green (966 files); suite-inventory, security-inventory,
  doc-links, wiring-reads, contract-markers, test-duplicates,
  durable-table-inventory, adr-index, adr-status-language, backlog-
  consistency, vulture-baseline (CI args), reachability, promotion-surface
  and radon-baseline gates all green.

## Paginated-read parity round (2026-11-26, salvage commit on auto-69)

The verify round left uncommitted work in the worktree; this round validated
and committed it. The gap it closes: ``get_entries`` reconstructs the signed
decision envelope and the store proof columns, but the shared page mapper
(``audit_pages.make_page``) did not, so any paginated read — Hive's
``audit_bridge`` included — handed back a signed row looking unsigned (#69).
``make_page`` now carries ``signature``/``signing_key_id``/``proof_type`` and
reuses ``decision_fields`` for the envelope, byte-for-byte the same readers
``get_entries`` uses. Two supporting decision-record repairs rode along:

- ``Sentinel._permission_denial_reason`` takes the already-resolved permission
  table instead of re-resolving it, so the denial reason and the signed
  ``policy_snapshot`` rest on one read and an unavailable source denies
  fail-closed (``authorize`` resolves once and passes it through).
- ``repair_action`` never carries evidence text unscrubbed: the
  missing-required-with-default rule names the field instead of echoing the
  schema default (a default can be a credential), and ``Violation`` redacts
  ``repair_action`` at construction, before signing — same invariant ``detail``
  has had since #1159. ``redact`` is idempotent, so rebuilding violations from
  a persisted row yields identical signed bytes.

New tests (+3 node IDs, delta re-derived +58 → +61):
``test_get_page_preserves_signed_decision_evidence`` (PG, mocked conn feeding
``make_page`` a row reconstructed from the store's own INSERT column list) and
the SQLite pair ``test_get_page_preserves_signed_decision_evidence`` /
``test_get_page_carries_decision_columns_from_durable_rows`` (real file-backed
store: signed round-trip through ``get_page`` re-verifies against a pinned
keyring; store-written decision columns survive the shared mapper).

Ledger note: the ``repair_action`` redaction reads ``self.repair_action``,
which flips vulture's classification of the field from unused to used. The
stale debt row
(``types/security.py::unused variable 'repair_action'``) was pruned from the
candidate ledger via ``--update`` with CI's exact scan args — 1219 → 1218
reviewed identities, one deletion, no additions — the gate's own
"fixed debt must be pruned" direction, not new banking and not a floor raise;
no grant needed and none used. Validation: targeted battery (pg/sqlite audit +
sentinel integrity + container wiring) 172 passed / 3 skipped (+3 vs the prior
169/3); ruff check/format clean; mypy battery 966 files clean;
vulture-baseline (CI args) exit 0.

## Independent verification round (2026-11-26, head cc15da1701)

Verifier re-executed every acceptance criterion at the assigned head
`cc15da1701852f02b80a47d313f62c121ba08d5c` (worktree clean, no code or test
changes in this round; recorded delta stays +61):

- Live PostgreSQL (pgvector/pg18 `maistro-pg-test` at 127.0.0.1:5433, private
  database `verify69_r1` created and then dropped): `alembic upgrade head`
  runs 001→071 as one linear chain with a single head
  (`071_sentinel_decision_integrity`); `MAISTRO_TEST_PG_DSN` pointed there,
  `test_pg_audit.py` + `test_integrity.py` give 80 passed / 0 skipped,
  including both real-PG tests (`-k real`: 2 passed).
- Targeted battery (sentinel integrity + pg/sqlite audit + audit pages +
  container wiring): 184 passed / 7 skipped (skips are the DSN-gated PG tests).
  `packages/maistro-core/tests/security` whole subtree: 1500 passed /
  25 skipped.
- Gates re-run at this head: `ruff check .` clean; suite-inventory
  (21 suites, 37229 IDs) ok; vulture-baseline with CI's exact args
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exit 0
  against base `3be6b66` (1219 → 1218 reviewed identities, matching the
  one-row `repair_action` prune); mypy AGENTS.md battery 966 files clean;
  durable-table-inventory, backlog-consistency, adr-index, adr-status-language
  and doc-links all exit 0.
- Hands-on (outside pytest): product allowed+denied `Sentinel.authorize`
  records sign and verify; SQLite persist→reload re-verifies against the
  pinned keyring; a self-consistent key-swap forgery (attacker key + valid
  signature over the same payload) is `UNKNOWN_KEY` under pinning and is
  documented as VERIFIED under embedded-only verification; all 15 protected
  fields tamper-rejected (violations via add/strip/alter on records that
  carry them); unsigned legacy row resolves `UNSIGNED`; rotation keeps the
  retired public key verifying while `DecisionSigner` holds only the active
  private key; raw `audit_log` rows contain no private-key material.
- Closure hygiene: no `fixes/closes/resolves` keywords in the PR body or any
  commit subject/body in `3be6b66..cc15da1701`; PR body says "Refs #69" only.
  `diff(3be6b66..cc15da1701)` is exactly the 22 declared surfaces;
  `quality/` vs `origin/develop` is the single vulture-baseline deletion.

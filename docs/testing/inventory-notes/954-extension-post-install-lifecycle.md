---
inventory-delta:
  packages/maistro-core/tests: +35
  packages/maistro-server/tests: +13
---
# 954-extension-post-install-lifecycle

M9-B3 finishes the extension lifecycle after activation (#954, epic #939),
on the same state machine the B2 lane (#953) installed — this lane merges
`auto-953` first so there is exactly one lifecycle authority, not a second
competing one. `packages/maistro-core/tests/extensions/test_post_install_lifecycle.py`
(+35) pins the service semantics; `packages/maistro-server/tests/api/test_extensions_lifecycle_api.py`
(+13) drives the new operator routes over the real router.

## What the core suite pins (35)

Each issue acceptance criterion has a test that would fail if the behavior
regressed, not just if a value changed:

- **Same-authority upgrades** (`TestSameAuthorityUpgrade`): the upgrade
  record's authority delta is empty against the active grant, the new grant
  equals the old one exactly, permissions display through the immutable
  snapshot check, the predecessor is superseded (retained, not deleted), and
  `resolve()` serves exactly the new version. Narrowing upgrades take the
  grant from the new snapshot; the pointer swaps once; upgrades without an
  active predecessor, downgrades-through-upgrade, and same-version-different-
  bytes are preflight refusals that leave `AWAITING_AUTHORIZATION` empty;
  byte-identical re-requests are idempotent; a candidate that fails trust at
  inspection is recorded REJECTED with the old version still serving.
- **Broader authority** (`TestBroadenedAuthorityReauthorization`): the delta
  names exactly the new permission, the loader receives zero calls before the
  explicit decision (activation before `authorize` raises `InvalidTransition`
  without touching code), and only the approved decision lets the broader
  grant through; denial leaves the current version serving.
- **Rollback** (`TestRollback`): a proven-compatible rollback re-activates
  through the loader seam with the exact bound bytes, swaps the pointer,
  retains the displaced version with a reason naming who rolled back and to
  what; substituted bytes, unsatisfiable dependencies (proven by moving the
  dependency partner past the old range), pins held at another version, and
  authority the current grant dropped all refuse **before the first state
  change** — asserted by comparing the full transition trail byte-for-byte
  across the refusal; broadened rollbacks require `allow_broadened` and then
  name the restored permissions in the audit trail; completed rollbacks retry
  without re-activating.
- **Disable** (`TestDisable`): `resolve()` returns None the moment disable
  returns; the record, its frozen grant and its trail survive verbatim (the
  disable transition is attributed and reasons are on the record); resume
  re-activates through the loader with the grant unchanged and refuses
  substituted bytes; disable is idempotent and refuses non-ACTIVE records.
- **Remove** (`TestRemove`): removal keeps the record (snapshot digest and
  frozen grant intact) and every transition queryable — the store's record
  dict is asserted to still hold the install id — while resolution stops and
  the (scope, extension, version) key is released so a reinstall opens a
  *fresh* authorization track (never resurrecting the removed record); the
  janitor purges only after the REMOVED transition is durable, its purge is
  reported as an audited note, janitor failures are recorded without
  restoring authority, and a remove retry re-runs a pending cleanup exactly
  once; removing a superseded record never disturbs the active one.
- **Idempotency + crash recovery** (`TestIdempotencyAndCrashRecovery`):
  upgrade retries neither re-run the loader nor fork a second authorization
  track; a loader crash mid-upgrade leaves a truthful FAILED record with the
  old version serving and recovers on the same bound artifact; both crash
  windows are constructed through the store and repaired by `reconcile()`
  (orphan ACTIVE superseded with a `system:reconciliation` transition;
  pointer-to-non-ACTIVE cleared, with `resolve()` shown safe even before the
  repair); a full install→upgrade→rollback→disable→remove run leaves both
  versions' provenance queryable in order.

## What the API suite pins (13)

The routes are the operator surface and add their own guarantees: the
upgrade endpoint pairs the record with the preflight report (empty delta
visible on the wire), activation before decision answers 409 with zero
loader calls, pins hold and release with the audited event trail, disable
flips `/resolution` to 404 immediately, removal keeps record + transitions
readable and lists (empty) removal notes, reconciliation requires workspace
authority (denial does not leak existence), and every write attributes the
authenticated principal — verified with two principals on one trail.

## What did not move

No B2 behavior changed where it was already pinned: all 106 prior core
extension tests and 12 prior API tests pass unmodified (the only B2-line
edits are the transition-table growth the issue requires and `inspect`
learning to skip REMOVED records when opening a track). The merge of the B2
lane added its own +118 under the note `953-extension-install-lifecycle`,
which travels with this branch.

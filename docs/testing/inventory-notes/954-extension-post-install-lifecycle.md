---
inventory-delta:
  packages/maistro-core/tests: +38
  packages/maistro-server/tests: +9
---
# 954 — Extension post-install lifecycle: pin, rollback, disable, remove (#954, M9-B3)

Adds the governed post-install lifecycle to the extension install state
machine (`packages/maistro-core/src/maistro/extensions/service.py`, store seam
in `store.py`, new states/edges in `types.py`) and the HTTP operator surface in
`maistro_server/api/extensions.py`, plus the suite that pins the epic's
acceptance criteria against reachable production behavior.

## packages/maistro-core/tests (+38)

`extensions/test_post_install_lifecycle.py` (38 cases) drives pin → upgrade →
rollback → disable → resume → remove through the real service and store:

- `TestPin` (7) — a pin holds the active version in place: activation of any
  other version raises `ExtensionPinned` until the pin is explicitly lifted
  (audited), re-pinning is an idempotent no-op, a scope holds at most one pin,
  and pin/unpin land on the same audit trail as state-shaped events.
- `TestDisableResume` (7) — disable clears the active pointer so the
  resolution seam answers nothing immediately (structural stop, not
  convention), every record and transition stays queryable, and resume
  re-crosses the loader seam with the same bound artifact; an unwired loader
  fails closed (record FAILED, pointer stays unset, nothing runs); a disable
  retried after a newer disable returns the newest suspended record, not the
  oldest.
- `TestFailedActivationRetry` (1) — a FAILED record cannot re-enter through
  the install gate to displace a newer active version with authority the
  active grant does not hold: the retry re-proves the rollback gates
  (`RollbackRefused`) before anything is touched.
- `TestRollback` (8) — rollback restores a superseded version through the
  loader seam only when its frozen grant declares no authority the active
  grant lacks and its manifest still evaluates compatible; otherwise
  `RollbackRefused` leaves the current version untouched (trail lengths
  pinned). Wrong payload records nothing; retrying a completed rollback with
  the same bytes is an idempotent no-op; rollback away from a pinned version
  is refused.
- `TestRemove` (9) — the janitor runs *before* any transition (a purge failure
  aborts with the record untouched), what it cleaned is recorded on the trail,
  removal is terminal for the record's authority while every record, snapshot,
  grant and transition stays queryable, the active pointer and any pin die
  with the record, pre-decision states cannot be removed, and re-removal is a
  no-op.
- `TestUpgradeAuthority` (3) — an update cannot silently increase declared
  authority: the broader request parks for explicit re-authorization and the
  grant afterwards is exactly the new snapshot's, never a silent union.
- `TestAuditAndIsolation` (3) — every lifecycle transition carries actor,
  org/workspace scope, version and a reason; the new states cannot reach
  ACTIVE without the loader; scope isolation holds for the new verbs.

## packages/maistro-server/tests (+9)

`test_extensions_api.py` adds `TestPostInstallLifecycleHttp` (9 cases) proving
the same verbs over the HTTP operator surface — pin → upgrade under a pin →
rollback → disable/resume → remove, with 409 refusals, the audited trail and
evidence retention asserted on the wire — plus four governed-refusal cases so
every lifecycle endpoint's error path is exercised over HTTP: pinning a record
that never reached ACTIVE (409), unpin/disable of an unknown install (404, no
scope leak), and removal of a pre-decision candidate (409 with the record still
parked for its decision).

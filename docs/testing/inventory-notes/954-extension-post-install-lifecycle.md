---
inventory-delta:
  packages/maistro-core/tests: +36
  packages/maistro-server/tests: +5
---
# 954 — Extension post-install lifecycle: pin, rollback, disable, remove (#954, M9-B3)

Adds the governed post-install lifecycle to the extension install state
machine (`packages/maistro-core/src/maistro/extensions/service.py`, store seam
in `store.py`, new states/edges in `types.py`) and the HTTP operator surface in
`maistro_server/api/extensions.py`, plus the suite that pins the epic's
acceptance criteria against reachable production behavior.

## packages/maistro-core/tests (+36)

`extensions/test_post_install_lifecycle.py` (36 cases) drives pin → upgrade →
rollback → disable → resume → remove through the real service and store;
`packages/maistro-server/tests/api/test_extensions_api.py` adds
`TestPostInstallLifecycleHttp` (5 cases) proving the same verbs over the HTTP
operator surface (409 refusals, audit trail, evidence retention):

- `TestPin` (7) — a pin holds the active version in place: activation of any
  other version raises `ExtensionPinned` until the pin is explicitly lifted
  (audited), re-pinning is an idempotent no-op, a scope holds at most one pin,
  and pin/unpin land on the same audit trail as state-shaped events.
- `TestDisableResume` (6) — disable clears the active pointer so the
  resolution seam answers nothing immediately (structural stop, not
  convention), every record and transition stays queryable, and resume
  re-crosses the loader seam with the same bound artifact; an unwired loader
  fails closed (record FAILED, pointer stays unset, nothing runs).
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

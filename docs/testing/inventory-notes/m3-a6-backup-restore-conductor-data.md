---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# m3-a6 — Prove backup/restore of authoritative converged state

Nine backend tests drive the real disaster-recovery drill functions from
`deploy/scripts/verify-restore.sh` (sourced, not reimplemented) against real
artifacts: a genuine age identity + `secrets.age` vault built with
`age-keygen`/`age`, and a real SQLite `state.db` carrying the canonical spine
tables. Issue #88's acceptance is about proof, not assumption, so each test
exercises a concrete drill outcome: the end-to-end pass (integrity manifest,
`state.db` integrity + canonical tables, historical Run IDs inspectable,
fencing versions preserved, escrowed `admin.key` actually decrypting the
backed-up vault), the pinned known-secret decrypt proof, and the four failure
modes the drill must catch loudly — absent credential escrow, an escrowed key
that is not THE vault identity, a corrupt backup component (manifest mismatch),
a missing component, and a truncated `state.db`. One test pins both deploy
scripts as valid bash (`bash -n`), since they live outside every pytest suite.

No production code moved; the drill scripts themselves live in `deploy/scripts/`
and are exercised as subprocesses, so the suite total gains exactly the nine new
new tests. The `age` tests skip cleanly (with the reason on record) where the age
toolchain is absent — CI's ubuntu runners and the dev container both have it.

## Develop-sync merge reconciliation (#88 + #1881)

Syncing this branch with `develop` merged #1881's rewrite of the restore
oracle (semantic evidence bound to one exported snapshot, four failure
classes) under this issue's Conductor-state proof. The two contracts compose
as follows, count-neutrally for the inventory:

- `verify-restore.sh` keeps #1881's semantic oracle as the PostgreSQL
  verification and gains #88's `verify_backup_manifest` /
  `verify_conductor_backup` as sourceable functions (the drill body moved
  into `main()`, so sourcing stays inert for the tests above); conductor
  failures map onto #1881's `artifact`/`verifier` classes with all asserted
  message substrings preserved.
- `tests/test_backup_permissions.py` and
  `tests/test_restore_oracle_characterization.py` (both #1881's, exercises of
  the PostgreSQL-only oracle) opt out of the Conductor capture with the same
  `SKIP_CONDUCTOR_BACKUP=1` contract `backup.sh` defines for Conductor-less
  stacks, and the former now expects the integrity manifest that `backup.sh`
  seals every real backup with. Test counts unchanged.

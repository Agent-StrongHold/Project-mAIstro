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
tests. The `age` tests skip cleanly (with the reason on record) where the age
toolchain is absent — CI's ubuntu runners and the dev container both have it.

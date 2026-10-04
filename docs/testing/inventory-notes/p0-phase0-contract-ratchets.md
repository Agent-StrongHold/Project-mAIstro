---
inventory-delta:
  packages/maistro-core/tests: +1
  tests/: +11
---
# p0-phase0-contract-ratchets

Workspace cutover Phase 0, steps P0.1 and P0.2: the principal-identity and
route-permission ratchets land with their baselines.

`packages/maistro-core/tests` moves by +1, and that net hides a swap.
`fitness/test_principal_identity.py` adds one ratchet test. In
`identity/test_extra_guard.py`, `maistro.identity` leaves the missing-extra
parametrization because the package now imports `Principal` without the
extra (two fewer cases). Two cases take their place: `Principal` imports
bare, and `ConductorSeed` still names the extra when it is first touched.
The installed-extra control keeps its two cases.

`tests/` gains +11: five in `test_check_principal_identity.py` (the scanner,
plus judging new and fixed entries against the trusted base) and six in
`test_check_route_permissions.py` (the registry entry contract, stale and
public entries, and grants for new exemptions). Neither imports the hive app;
the repo-level runs are the `quality.yml` steps beside `check_enumerations.py`.

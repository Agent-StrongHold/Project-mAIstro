---
inventory-delta:
  tests/: +2
---
# #2445: license-exception ledger binds to the real lockfiles

The @axe-core/playwright 4.10.2 → 4.14.0 bump added explicit
`"license": "MPL-2.0"` rows to `packages/hive-conductor/tests/e2e/package-lock.json`
(newer npm records license fields in lockfile entries; the 4.10.x rows carried
no license data and passed as missing-data, which `check_licenses` counts but
never fails). `scripts/js_dependency_gate.py` therefore gained its first two
`LICENSE_EXCEPTIONS` entries, and this change adds two root-suite node IDs
that pin the ledger to reality in both directions:

- every real-lockfile (package, license) pair an exception covers must list
  its installed version in the exception's `versions` — an exception keyed
  without the version actually present would approve a version nobody
  triaged;
- every reviewed version in the ledger must still be locked in some real
  surface — a version no lockfile installs is a stale row whose rationale no
  longer describes the tree.

The second direction also pins the fixture: if the MPL-2.0 rows ever vanish
from the lockfile format again, the forward loop would exercise nothing, so
the test fails loudly instead of passing vacuously.

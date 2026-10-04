---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# Issue #399 — Stop seeding a fabricated CRITICAL vulnerability on fresh installs

`stores._seed_messages` used to run on every boot in every mode, and one of its
three rows was a fabricated CRITICAL security finding ("XSS in /v1/auth/callback"
from "RedTeam", priority critical, category security). Every fresh install —
including a security-focused product's very first login — booted looking
compromised, and no reviewer could tell that fiction from a real finding.

The fix follows the #840 precedent that already scoped the fabricated agent
roster to demo mode:

- Production (the default `hive_mode`) seeds no messages at all — an empty inbox
  renders as "no messages", the same honesty rule the audit log already follows
  (the audit-log seed was removed for exactly this reason earlier).
- The fixture survives only behind the explicit demo mode
  (`hive_mode == "demo"`), which is the same isolation the fabricated roster and
  the in-process task backend already require.
- Every demo row now carries machine-readable synthetic provenance:
  `synthetic=True` on the `Message` model (the field only the demo seeder can
  set — `CreateMessageBody` has `extra="ignore"`, so the API offers no way to
  forge the stamp) plus deterministic `msg-seed-*` ids, so demo data is
  unmistakable and trivially removable by id.

## Suite delta

Nine new backend tests in
`packages/hive-conductor/backend/tests/test_fresh_install_security_truthfulness.py`:

- three pin that a full production boot leaves the inbox empty, naming the
  fabricated CRITICAL XSS row explicitly, including a second-boot repeat;
- three pin the demo-mode fixture: it still seeds, every row is stamped
  `synthetic=True`, and re-seeding is deterministic;
- three drive the HTTP surface: a fresh install answers `/v1/messages` with
  `[]`, `?category=security` with `[]`, and unread-count with `0` (the E2E
  empty-truthful-state assertion); a POST cannot forge `synthetic`; demo rows
  are readable and deletable by id over the API.

All nine fail against the pre-fix tree (verified in a throwaway worktree at the
base commit) and pass against the fix.

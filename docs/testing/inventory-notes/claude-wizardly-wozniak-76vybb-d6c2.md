---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# claude-wizardly-wozniak-76vybb-d6c2

CI-repair round for the `commit status not successful` lane failure at head
`00fc154f81c3`: hosted CI `lint-and-type-check` failed at the
"Every unauthenticated path is declared and justified" step because the two
`temporary` exemptions in `quality/public-routes.json` (`/v1/auth/register`,
`/v1/setup/`) expired on 2026-11-24. The registry's own text names the
remedies: close it (#313) or re-justify with a new date. Re-justifying a
high-risk anonymous write path is the owner's reviewed decision, so this
round closes instead — implementing the narrowing the ledger already
documented as #313's intent ("Narrowing it to the pre-setup window is part of
#313") and that `quality/route-permissions.json` already declares
(`/v1/setup`: `exempt_reason: "authenticated-only"`).

Net public surface: 12 → 11 route identities (a reduction; `/v1/setup/`
removed from the registry and made public only inside the pre-setup window,
the same fail-closed boundary `/v1/install/` already uses).
`/v1/auth/register` stays public by design — the durable registration policy
inside the handler is now the boundary the temporary exemption was waiting
for — so its row converts from expired-`temporary` to `permanent` with that
reason on the record.

## Test delta (+6, packages/hive-conductor/backend/tests)

`tests/test_auth_middleware.py` gains `TestSetupPreSetupWindow`, mirroring the
existing `TestInstallPreSetupWindow`: post-setup 401 for wizard reads and for
the one-shot completion endpoint, public pre-setup, `status`/`presets`
surviving the narrowing, fail-closed when setup state is unreadable,
boundary-safe sibling matching, and a lock against reintroducing the prefix in
`_PUBLIC_PREFIXES`. `test_setup_first_run_questions.py` needs no count change:
its `_served_questions` helper now opens the pre-setup window the same way
(that test file's HTTP calls run on the provisioned conftest app).

Locally: the full `packages/hive-conductor/backend/tests` suite passes
(4592 collected, 4512 passed + 80 skipped) and the earlier merge round's
`tests/: +0` stands — no root-suite change.

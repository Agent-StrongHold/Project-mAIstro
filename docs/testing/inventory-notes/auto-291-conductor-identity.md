---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# Auto 291 Conductor identity contract

Adds backend test nodes for the Conductor deployment contract: the health
probe distinguishes a supported no-crypto profile, operational provisioned
identity, selected-but-unprovisioned identity, and missing identity runtime.
The operational case decrypts and derives the persisted root; malformed roots,
DID-mismatched roots, missing records, and unavailable vaults are all
misconfigured. The existing API health tests also assert that identity status is
exposed on both liveness and readiness without making optional identity an
outage before setup. Setup still refuses to create accounts when identity
persistence fails. Browser coverage now verifies that unavailable and
misconfigured health responses disable the Crypto Identity action, executed
locally with Playwright against a live backend (8/8 passing, including the
full five-step setup completion).

Merge reconciliation: develop's font-size normalization (8/11 -> 12) was
carried into the identity-gated module card copy, and develop's conditional
`bip-utils` marker ("avoid the Python 3.14 path") was superseded by the
pinned cp312/cp313 wheel set this contract ships on Python 3.13.15. The
e2e spec was repaired for drift that predates this branch: the wizard grew
an Accounts step (five steps, not four), the header copy is "🐝 Hive
Conductor", and module/step selectors were tightened to role and exact-text
locators; security CI covers both image profiles with in-image import
assertions.

Independent verification addendum (head c932f42b, post-develop-merge):

- Re-executed at this exact head: driver gates (ruff check/format clean;
  extra_guard 6 passed; targeted conductor files 55 passed; suite inventories
  match) plus engine identity tests 69 passed, full conductor backend suite
  2663 passed (matches recorded inventory), prepull/wheel-import tests 43
  passed. The real-vault provisioning test executed (host age present), not
  skipped.
- Both Docker profiles rebuilt from this tree: default and
  INSTALL_OBSERVABILITY=1. The in-build smoke test (exact CPython 3.13.15,
  pinned bip-utils/coincurve/pynacl versions, ConductorSeed derive) passed in
  both builds; the security.yml in-image verification commands were replicated
  verbatim against both fresh images and printed
  identity=operational/observability=importable.
- Live Playwright run of frontend/e2e/setup.spec.ts against the freshly built
  default image: 8/8 passed, including unavailable- and misconfigured-health
  gating (toggle disabled, "no action offered") and full five-step setup
  completion. Fresh /health shows identity=misconfigured/setup_incomplete,
  identity_required=false pre-setup, as specified.
- Residuals: frontend/e2e still has no CI owner (compose e2e runs tests/e2e
  only); GitHub Actions execution of the security container job remains
  UNVERIFIED, and that job is scoped to PR-to-main/main pushes/nightly, so it
  will not fire on this develop PR — local replication above is the evidence
  of record.

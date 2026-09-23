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

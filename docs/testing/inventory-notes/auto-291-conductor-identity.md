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
persistence fails.

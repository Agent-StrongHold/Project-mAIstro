---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# Auto 291 Conductor identity contract

Adds four backend test nodes for the Conductor deployment contract: the health
probe distinguishes a supported no-crypto profile, operational provisioned
identity, selected-but-unprovisioned identity, and missing identity runtime.
The existing API health tests also assert that the identity status is exposed on
both liveness and readiness without making optional identity an outage before
setup. Additional nodes verify a missing encrypted seed is misconfigured and
that setup refuses to create accounts when identity persistence fails.

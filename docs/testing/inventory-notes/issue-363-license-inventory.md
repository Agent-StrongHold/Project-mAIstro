---
inventory-delta:
  tests/test_check_license_inventory.py: +7
---
# Issue 363 license inventory

Added seven tests for `scripts/check-license-inventory.py`. The cases cover
component/evidence identity reconciliation, unknown metadata, reviewed
resolutions, copyleft classification and legal policy, missing required
surfaces, and malformed SBOM identities.

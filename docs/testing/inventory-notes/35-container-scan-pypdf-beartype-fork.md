---
inventory-delta:
  tests/: +3
---
# Issue #35 CI repair — pypdf CVE fix and fork-aware image-lock reconciliation

Two changes, one test-adding:

1. **`uv.lock`: pypdf 6.21.1 → 6.21.2** (transitive via browser-use in the
   `maistro-engine-research` image). The trivy step of the
   "Container scan + SBOM + cosign" job failed on pypdf 6.21.1 HIGH CVEs
   (fixed in 6.21.2) even after the previous repair round; the lock bump
   removes the findings at the root. No test change; the rebuilt image scans
   clean and `check-image-lock-reconciliation` and the pip-audit gate pass at
   CI's exact invocations.

2. **`scripts/check-image-lock-reconciliation.py`: fork-aware expected side.**
   The previous repair's fastmcp-slim 4.1.3 bump made the lock fork beartype
   (`0.22.9 ; python_full_version < '3.15'`, `0.23.1 ; >= '3.15'`). The gate
   kept only the last expected line per name, so every py<3.15 image — the
   research image provably included, rebuilt and reconciled locally — reds the
   reconcile step of the same CI job as soon as trivy passes. `parse_expected`
   now also returns the per-name version set, and a skew means "ships a
   version no fork of the lock allows". Single-version names behave exactly as
   before; a shipped fork partition reconciles; an unlocked version still
   fails, named against every allowed fork. No gate weakened.

Tests added in `tests/test_check_image_lock_reconciliation.py` (+3, suite 30
total): `test_parse_expected_records_every_fork_version`,
`test_forked_pin_shipping_one_partition_reconciles`,
`test_forked_pin_shipping_an_unlocked_version_fails`. The fails-before /
passes-after pair was also shown against the real rebuilt research image:
the pre-fix script exits 1 with `version mismatch: beartype==0.22.9 (image)
!= beartype==0.23.1`, the fixed script exits 0.

---
inventory-delta:
  tests/: +1
---

# Issue #89: gate irreversible PyPI publication on validated soak

`tests/test_promote_release.py::test_pypi_waits_for_the_soak_gate_before_irreversible_publication`
checks the real `release.yml` job dependency graph: `pypi` must require successful
`images` (where `adopt-digests` rejects missing/failed/unbound soak evidence and
unrouted findings). It also pins fail-closed job/step behavior and preserves the
`release` approval environment. Previously both jobs depended on `wheels` and
could run in parallel: valid wheel hashes alone permitted PyPI publication.

This complements existing executable missing-soak and unrouted-findings CLI
tests; a static schema validator without a required dependency cannot prevent
publication. Operational RC/soak/promotion execution remains unproven.

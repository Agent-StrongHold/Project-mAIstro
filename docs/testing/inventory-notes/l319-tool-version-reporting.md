---
inventory-delta:
  tests/: +24
---

# L319 tool-version reporting: required Provenance.tool_version

Bounded #319 repair (isolated lane `foreman/319-tool-version-20261017`,
base `ac737014`): every ratchet provenance record now names the analyzer
implementation that measured it, and the shared `ratchet_provenance.py`
grew the two identity helpers (`bundled_implementation_fingerprint`,
`installed_distribution_version`).

## Why the `tests/` count moved (+24, computed)

- `tests/test_ratchet_provenance.py` **+20** — the required-field contract
  (omission raises, blank/None raises, no fallback), `as_dict`/render
  distinctness between `tool_version` and `metric_definition_version`,
  fingerprint determinism across root paths, sensitivity to delegated-source
  edits, length-framing disambiguation, and the refused states (empty
  manifest, missing source, outside-root x2, unreadable source); installed
  distribution observed vs. missing (+2); and the executable constructor-map
  witness that all 22 production call sites wire `tool_version=` explicitly,
  every bundled manifest names files that exist, and the mutation gate never
  attests an installed cosmic-ray version (+3).
- `tests/test_check_vulture_baseline.py` **+2** — the trusted run reports the
  installed vulture version, and a distribution that cannot be resolved fails
  the run instead of reporting `unknown`.
- `tests/test_m1_542_diff_coverage_edges.py` **+2** — mutation version
  resolution failure writes no baseline/health artifact on either write path
  (clear `::error::`, exit 2), and the quality-clean scheduler run passes 0
  while reporting the real bundled `bundled-sha256:` identity.

Computed with `scripts/check-suite-inventory.py --suite tests/` (expected
5206, collected 5230 → +24), not estimated. No other suite moved.

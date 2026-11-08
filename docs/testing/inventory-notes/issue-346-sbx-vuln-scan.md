---
inventory-delta:
  tests/: +7
---
# issue-346: sbx producer vulnerability scanning + AC-4 exception shape

Closes nothing by itself; Refs #346 (the research/rsi boot-smoke port is a
separate parallel lane, and #346 closes when both land).

## What moved the count

`tests/test_check_image_inventory.py` +7 (46 → 53 collected):

- `test_an_exception_without_an_expiry_is_a_permanent_exemption`
- `test_an_exception_with_a_lapsed_expiry_no_longer_excuses_anything`
- `test_an_exception_with_a_malformed_expiry_fails`
- `test_an_exception_without_a_version_scope_can_widen_silently`
- `test_the_sbx_producer_script_fails_closed_on_an_unpinned_scanner`
- `test_the_sbx_producer_scans_carry_the_blocking_policy`
- `test_the_sbx_producer_scans_run_before_any_push`

The first four pin the extended `check_exception` in
`scripts/check-image-inventory.py` (AC-4's version-scoped + expiring shape:
`version_scope` required, `expires` required as YYYY-MM-DD, lapsed exceptions
fail like lapsed trivyignore entries). The last three are structural pins on
`deploy/sbx/build.sh`: trivy/grype required on PATH at exactly CI's pinned
versions (0.73.0 / 0.116.0) with refusal on mismatch, scans carrying the
blocking policy flags (`--severity HIGH,CRITICAL --exit-code 1
--ignore-unfixed`, `--fail-on high --only-fixed`), and both scans ordered
before `docker push` / `sbx template load` so a vulnerable image cannot leave
the producer.

All seven fail against the pre-change tree (verified by stashing the four
touched non-test files and re-running: 7 failed / 46 passed) and pass with
the change (53/53).

## Untouched counts

No other suite moved: the change touches no package source, only
`deploy/sbx/build.sh`, `scripts/check-image-inventory.py`,
`quality/image-inventory.json`, `quality/shipped-surface-truth.json` (the
#382 known-facade row refresh: `unresolved` → `resolved` with the PR #1887
truthful-501 evidence), and this test file.

---
inventory-delta:
  tests/: +14
---
# feat-55-direct-effect-inventory-9471

Fourteen new tests in `tests/test_check_direct_effects.py`, closing the diff-coverage
gap the #55 direct-effect inventory gate opened at 89.8% (needed 90%). All additive,
targeting branches the 13 original tests never exercised:

- `test_production_python_files_is_empty_without_a_packages_dir` — no `packages/`
  directory yields no files rather than raising.
- `test_star_import_is_skipped_by_alias_collection` — `from x import *` does not
  become a spurious alias entry.
- `test_environment_default_via_keyword_argument_is_detected` /
  `test_environment_lookup_without_a_default_yields_no_endpoint_text` — the
  `os.environ.get`/`os.getenv` default-literal resolver's keyword-argument branch
  and its no-default branch.
- `test_http_url_via_keyword_argument_is_detected` — `client.post(url=...)`, not
  just the positional form the original tests covered.
- `test_syntax_error_source_yields_no_sites` — a source string that fails to parse
  is treated as non-production input, not a crash.
- `test_discover_skips_a_file_that_cannot_be_read` — a broken symlink under
  `packages/` is skipped rather than aborting the scan.
- `test_discover_rejects_duplicate_site_identities` — two sites sharing one
  identity raise, rather than silently overwriting each other in the inventory.
- `test_audit_reports_a_field_mismatch_between_recorded_and_discovered` — a
  recorded entry whose fields disagree with the discovered site is flagged, not
  just missing/extra sites.
- `test_write_inventory_preserves_disposition_and_drops_id` — `--update` carries
  forward an existing disposition/owner/rationale and never writes the redundant
  `id` key.
- `test_main_fails_when_inventory_file_is_missing`,
  `test_main_update_writes_inventory_and_returns_zero`,
  `test_main_reports_failures_and_returns_one_when_inventory_is_stale`,
  `test_main_succeeds_when_inventory_matches` — `main()`'s four paths (missing
  inventory, `--update`, stale inventory, clean inventory), previously exercised
  only indirectly by running the script itself in CI rather than by the test suite.

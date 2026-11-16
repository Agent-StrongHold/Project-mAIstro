---
inventory-delta:
  packages/maistro-registry/tests: +6
  tests/: +12
---
# 812-registry-test-path-resolution

Issue #812: every cited registry `tests:` path must resolve to a real test.

## What moved

`tests/` +12 — eight CLI-level cases in `tests/tools/registry/test_cli.py`
and four validator-level cases in `tests/tools/registry/test_validator.py`:

- `TestCitedTestPaths` (4): a dead cited path fails `lint --strict` (the AC-3
  regression), fails plain `lint` too (a false evidence claim is an error, not
  a style nit), a live path passes, and a `path::node_id` suffix cannot mask a
  dead file.
- `TestContractsWithoutTests` (4): contracts with an empty `tests:` list warn
  and fail strict when the document claims a proof status (Implemented /
  Tests Passing), record an explicit non-failing debt otherwise, and stay
  clean when tests are cited or no contracts are declared.
- `test_validator.py` (4): the same classification at the `validate_file`
  layer, including rendering (`WARN:` / `DEBT:`) and the clean paths.

`packages/maistro-registry/tests` +6 — new `test_test_paths.py` unit-testing
`check_test_paths` directly: node-id portion stripping, existing file and
suite-directory resolution, dead file/directory/empty-portion failures, and
the path-escapes-repository-root refusal.

## Why

Front matter validated `tests:` as strings and nothing resolved them, so a
document could cite deleted or never-written tests and stay registry-green
while other gates (ADR-097's lifecycle machine) treat the field as evidence.
The check lives in `maistro_registry.test_paths`, wired into `lint` as an
error; the no-evidence contracts state is surfaced per document as a warning
(proof-claiming statuses) or an explicit counted debt (everything else), so
the corpus's 205 pre-existing contracts-without-tests documents show up in
every lint summary without turning the strict gate red for a backlog lint
cannot fix. Fourteen documents carried dead citations and are dispositioned
in the same change — repointed to the shipped coverage or emptied with a
per-document prose note, never ignored wholesale.

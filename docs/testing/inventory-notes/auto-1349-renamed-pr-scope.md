---
inventory-delta:
  tests/: +3
---
# auto-1349-renamed-pr-scope

Three additions to `tests/test_check_gates_ran.py` for #1349 (include
`previous_filename` when classifying renamed PR files for gates-ran scope):

- two envelope cases: a rename recorded with both paths in
  `changed-files.json` puts the moved file's old location in scope for the
  specialized legs, in either direction (out of `packages/maistro-core/src/**`
  and back in), so a skipped specialized check on the old path is not
  discarded as out of scope;
- one node-executed case that runs the actual "Collect changed files for
  pull-request scope" script from `.github/workflows/gates-ran.yml` against a
  mocked `listFiles` response (skipped where `node` is unavailable): a rename
  contributes both `filename` and `previous_filename`, an unrenamed file
  contributes only itself, and a rename without `previous_filename` leaks no
  `undefined` entry into the envelope.

No existing cases were removed or renamed; the root-suite count moves +3.

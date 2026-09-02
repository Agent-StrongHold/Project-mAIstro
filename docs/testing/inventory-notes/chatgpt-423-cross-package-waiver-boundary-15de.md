---
inventory-delta:
  tests/: +5
---
# chatgpt-423-cross-package-waiver-boundary-15de

Five cases added to `TestMutationBoundaries` in
`tests/test_check_cross_package_imports.py`, one per genuine mutation survivor
this PR set out to kill (#423). They are the five its description lists: a
trailing waiver cannot suppress a first-line finding (`index > 0` ->
`index >= 0`), a plain dotted import binds the top-level name, an aliased
dotted import binds the alias, `_collect` continues past a `TYPE_CHECKING`
block, and `_imports_in.walk` does too.

No production code changes, and the existing preceding-line waiver test is
untouched, so the whole delta is those five.

**Net of a removal.** The branch also carried
`tests/test_tmp_423_ruff_diff.py`, whose own docstring called it a "Temporary
formatter diagnostic for PR #726; removed after capturing Ruff's diff" and
whose single test body ended in `pytest.fail(proc.stdout + proc.stderr)` — it
failed unconditionally by construction, which is what the `test` and coverage
legs were reporting. It is deleted here, and the formatting delta it existed to
reveal is applied: `ruff format` had two wrapped signatures and a comprehension
to reflow in `test_check_cross_package_imports.py`, which is what
`lint-and-type-check` was failing on. So the raw arithmetic is six added minus
one removed.

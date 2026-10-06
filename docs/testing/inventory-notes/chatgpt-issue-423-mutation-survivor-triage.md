# #423 cross-package import mutation survivor triage

Parent run: #419, against `scripts/check-cross-package-imports.py` with `tests/test_check_cross_package_imports.py` as the targeted test file.

This note is category-complete for the survivors recorded in #419. The parent issue preserved survivor categories rather than cosmic-ray job IDs.

## Genuine gaps covered by #423

- `_is_waived`: `index > 0` mutated to `index >= 0`. A first-line finding must not consult `lines[-1]`; the direct first-line/trailing-waiver test kills this.
- `_imported_by`: `alias.asname or ...` mutated so an unaliased dotted import no longer binds its top-level name. The plain `import json.encoder` target-module test constrains the binding to `json`.
- `_imported_by`: `.split(".")[0]` mutated to select the final component. The same dotted-import test distinguishes the runtime binding `json` from `encoder`.
- `_collect`: `continue` after a `TYPE_CHECKING` block mutated to `break`. This is genuine because a later module-scope runtime binding would disappear from the presented-name set. #423 must retain a direct test with a runtime name after a `TYPE_CHECKING` block.
- `_imports_in.walk`: `continue` after a `TYPE_CHECKING` block mutated to `break`. This is genuine because later sibling imports would no longer be scanned. #423 must retain a direct test with a bad runtime import after a `TYPE_CHECKING` block.

## Equivalent or intentionally filtered survivors

- Annotation-position `BinOp` mutations under `from __future__ import annotations`: equivalent by construction because those annotations are postponed and not evaluated. #419/#422 owns filtering this class while retaining runtime-union mutations.
- `index < len(lines)` mutated to `index is not len(lines)` in `scan`: equivalent for reachable inputs. `index` is `ast`'s 1-based import `lineno - 1`; after a successful parse, every reported import line necessarily maps to an existing element of `text.splitlines()`, so `0 <= index < len(lines)` and `index != len(lines)` are both true. Manufacturing an out-of-range index would test a state `scan` cannot produce.
- `name == "*"` mutated to identity comparison in the recorded run: equivalent under the supported CPython runtime for the one-character `"*"` AST import name, which is interned. The product contract remains value equality; this survivor is runtime-representation noise rather than an unresolved import behavior gap.
- The `if __name__ == "__main__"` guard comparison survivor: equivalent for this mutation packet because the targeted pytest command imports the script as a module and never executes its CLI guard. It does not exercise or claim CLI-main comparator semantics.

No production behavior is changed by this triage. The production predicate and import binding logic are already correct; #423 strengthens the tests around the genuine survivor boundaries.

## Closeout verification (2026-10-06, `a8258ee2`)

The triage above was category-level; the closeout asked for exact source/operator/test
identities and a reproduction of the named mutation against the current focused test.
Both were executed against this tree. The working tree was byte-restored after every
mutant experiment (the `mutation_packet._restored` pattern); `git status` stays clean.

### Full packet, current tree

cosmic-ray 8.7.0, `worker-count = 4`, per-mutant `timeout = 60.0`, test command
`pytest tests/test_check_cross_package_imports.py --timeout=20 -q -x`,
`scripts/mutation_filter_annotations.py` applied between `init` and `exec`:

| | |
|---|---|
| Mutants | 506 |
| Skipped by the annotation filter | 44 (all annotation-position `BinOp`: the signature unions at L130 `Path | None`, L141 `ast.Import | ast.ImportFrom`, L151 `ast.Assign | ast.AnnAssign | ast.AugAssign`) |
| Executed | 462 |
| Killed | 462 |
| Survivors reported | 0 |
| Adjusted kill rate | 1.0 |

### The five genuine survivors: killed, exact identities

Each mutant below was also applied to a scratch copy of the gate and the actual test
file run against it **without** `-x`, so the killing test is named, not inferred from
`-x`-shortened output. A pristine control run of the same harness passes everything
the scratch layout can exercise.

- `scan`/`_is_waived` L290 `core/ReplaceComparisonOperator_Gt_GtE`: `index > 0` ->
  `index >= 0` -- killed by
  `TestMutationBoundaries.test_last_line_waiver_does_not_suppress_first_line_finding`,
  and by nothing else: it is the only test that fails under the mutant beyond the
  control baseline.
- `_imported_by` L147 `or` -> `and` -- killed by
  `TestMutationBoundaries.test_dotted_import_alias_binds_the_alias_not_the_top_level_name`
  (an aliased dotted import must bind the alias, not the top-level name) and by
  `TestMutationBoundaries.test_plain_dotted_import_binds_the_top_level_name`
  (for an unaliased import `alias.asname` is `None`, so the mutant records `None`
  instead of the top-level name and the test's first no-finding assertion fails).
- `_imported_by` L147 `.split(".")[0]` -> `[-1]` -- killed by
  `TestMutationBoundaries.test_plain_dotted_import_binds_the_top_level_name`.
- `_collect` L199 `core/ReplaceContinueWithBreak` -- killed by
  `TestMutationBoundaries.test_collect_continues_after_type_checking_block`.
- `_imports_in.walk` L314 `core/ReplaceContinueWithBreak` -- killed by
  `TestMutationBoundaries.test_import_scan_continues_after_type_checking_block`.

### The equivalent rows: re-confirmed under the mutant, not just argued

The packet reported the comparison mutants below as killed. The cause recorded
earlier (per-test `--timeout=20` contention) was wrong and is retracted: the two
whole-tree tests in `TestTheRepository` carry `@pytest.mark.timeout(120)`
(`tests/test_check_cross_package_imports.py:189` and `:211`), and a per-test
marker overrides the `--timeout` flag, so worker contention cannot push those
tests over a 20-second limit. No worker output survives from the #419 run to
inspect, so the kill cause is left unverified; cosmic-ray's own `timeout = 60.0`
process limit is the remaining candidate. What the closeout re-run does
establish, independently of cause: each mutant was applied to the working tree
and the full focused suite run **without** `--timeout`: 58 passed in every case,
so no test kills them and the equivalence records above stand as written.

- `scan` L388 `core/ReplaceComparisonOperator_Lt_IsNot`: `index < len(lines)` ->
  `index is not len(lines)` -- unreachable-input equivalent, as recorded above.
- `_resolve` L348 `core/ReplaceComparisonOperator_Eq_Is`: `name == "*"` ->
  `name is "*"` -- single-character string cache equivalent, as recorded above.
- module guard L547 `core/ReplaceComparisonOperator_Eq_LtE`:
  `__name__ == "__main__"` -> `__name__ <= "__main__"` -- holds for both reachable
  module names, as recorded above.

(`__name__ != "__main__"` and the strict-ordering siblings are a different story: those
mutants make the CLI print nothing when run as a script, and
`TestTheRepository.test_the_script_exits_zero_on_the_real_tree` genuinely kills them.)

### Scope notes

- `quality/mutation-baseline.json` still has `entries: {}` -- arming the ratchet is
  #419's criterion, not #423's, and this change touches no `quality/` ledger.
- Acceptance criterion "a waiver on the line immediately above a finding still
  suppresses it, at every index but 0": `TestTheEscapeHatch.test_a_waiver_on_the_line_above_suppresses`
  pins index 1 -- the index the fix could most plausibly have broken -- and passes
  unchanged under the `>= 0` mutant; the `index > 0` guard structurally preserves every
  index above it, and `test_a_waiver_two_lines_above_does_not_reach` pins the no-overreach
  side at index 2.

### Independent in-tree re-verification (2026-10-06 salvage, `0e1a1257`)

Each disposition above was re-executed with the mutant applied directly to the working
`scripts/check-cross-package-imports.py` (not a scratch copy), byte-restored and
sha256-compared after every run (`87b8f28ab7f25215...` intact), against
`pytest tests/test_check_cross_package_imports.py -q -rf` with no `--timeout` and no
`-x`. Pristine baseline: 58 passed.

- L290 `Gt` -> `GtE`: 1 failed, 57 passed -- the only failure is
  `test_last_line_waiver_does_not_suppress_first_line_finding`, confirming "and by
  nothing else" exactly.
- L147 `or` -> `and`: 2 failed, 56 passed -- both dotted-import tests, matching the
  corrected attribution above.
- L147 `.split(".")[0]` -> `[-1]`: 1 failed, 57 passed -- only the plain dotted-import
  test.
- L199 `continue` -> `break`: 3 failed, 55 passed --
  `test_collect_continues_after_type_checking_block` plus the two real-tree
  `TestTheRepository` tests, consistent with the genuine-gap rationale.
- L314 `continue` -> `break`: 1 failed, 57 passed -- only
  `test_import_scan_continues_after_type_checking_block`.
- L388 `Lt` -> `IsNot` / L348 `Eq` -> `Is` / L547 `Eq` -> `LtE`: 58 passed in every
  recorded run. One earlier `Lt` -> `IsNot` execution showed a single transient failure
  whose identity was not captured; the mutant's semantics are identical on every
  reachable input (`index < len(lines)` and `index is not len(lines)` are both true
  whenever `0 <= index < len(lines)`, and `scan` cannot produce `index == len(lines)`),
  so a genuine kill is impossible there, and the suite passed 58/58 on the three
  recorded runs since plus the pristine control.

The retraction above was independently confirmed: `@pytest.mark.timeout(120)` sits at
`tests/test_check_cross_package_imports.py:189` and `:211`, and a per-test marker
overrides the packet command's `--timeout=20` default, so the original load-noise
explanation was impossible as written.

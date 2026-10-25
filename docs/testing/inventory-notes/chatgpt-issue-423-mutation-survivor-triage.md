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

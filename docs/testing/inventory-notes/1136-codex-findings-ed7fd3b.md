---
inventory-delta:
  tests/: +8
---
# Global/TypeAlias/PEP-695 review repairs (#1136)

Eight new cases in `tests/test_check_execution_lifecycle_codex_findings.py`
address three of the five findings from the Codex review requested on exact
head `ed7fd3bb99842811d76b10712ce1e715984c2e43`. Each was independently
reproduced against that head before being fixed, following the same
discipline as the prior rounds in this PR.

Fixed here:

- **`global` inside a function got the wrong identity.** `global RunStatus`
  followed by `RunStatus = Literal[...]` in a function body makes that a
  module-level assignment at runtime, but the scanner reported it under the
  function-qualified identity (`pkg.mod::configure.RunStatus`) instead of the
  real one (`pkg.mod::RunStatus`). An already-authorized local-scoped name
  could therefore mask a distinct new global execution authority. `scope()`
  now collects `global` declarations for the function once, and `_assignment`
  uses the module-level identity for any name so declared. A sibling function
  that does not declare `global` still gets its own function-qualified
  identity -- the fix does not conflate the two.
- **PEP 613 explicit `TypeAlias` strings were inert.** `x: TypeAlias =
  "Literal['pending', 'running', 'failed']"` is Pyright-valid type syntax, not
  a runtime string, but the scanner treated it as ordinary string data and
  reported no vocabulary. `_assignment` now recognizes an `AnnAssign` whose
  annotation resolves to `typing.TypeAlias` (tracked the same way
  `Literal`/`Optional`/etc. are) and parses the quoted RHS as a type
  expression, reusing the existing forward-ref parser. A `TypeAlias`-annotated
  string that isn't valid type syntax, and an ordinary unannotated string
  assignment, both still resolve to nothing.
- **PEP 695 type parameters leaked the outer scope.** `type RunStatus[Values]
  = Values` and `class Box[T]: status: T` bind `Values`/`T` as parameters
  local to the alias/class, but the live-environment lookup used for lazy PEP
  695 resolution only ever saw the outer scope, so a same-named outer alias
  was falsely reported as the generic's vocabulary. `scope()` now masks each
  definition's own `node.type_params` before resolving its body/value; a
  generic alias whose value does not reuse a type-parameter name still
  resolves normally.

Not fixed here (verified as real, left for a follow-up):

- **Conditional-branch shadowing evades detection.** `if False: Literal =
  str` followed by `RunStatus = Literal[...]` erases the `Literal` binding
  for the rest of the scope even though the branch never executes, silently
  producing an empty vocabulary. This needs branch-aware environment merging
  (the scanner currently treats every branch as unconditionally sequential),
  which is a larger design change than the fixes above and is not attempted
  in this commit.
- **Trusted-base lookup uses the head-tree path.** `_discover_at_revision`
  looks up each module's pre-existing source with `git show
  <base>:<path-at-head>`; a file moved or restructured between the trusted
  base and the candidate (e.g. `pkg/foo.py` -> `pkg/foo/__init__.py`) fails
  that lookup and the pre-existing vocabulary is misreported as newly added,
  demanding authorization it doesn't need. Fixing this needs a revision-aware
  module/path mapping rather than reusing `_collect_modules()`'s head-tree
  view, which is out of scope for this commit.

All 171 tests across the seven published lifecycle suites plus this file
pass. Reverting only the scanner to the pre-fix state (keeping this test
file) makes all 5 new global/TypeAlias/type-parameter cases fail and the 3
existing sanity cases (non-`global` sibling, non-`TypeAlias` string,
non-shadowed generic) still pass. `ruff check`/`ruff format --check` are
clean, and the real-repository gate still reports 19 classified work-state
vocabularies with no new unauthorized debt.

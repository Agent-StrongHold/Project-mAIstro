---
inventory-delta:
  tests/: +4
---
# Conditional-branch rebinding guard (#1136)

Four more cases in `tests/test_check_execution_lifecycle_codex_findings.py`
fix the fourth of the five findings from the Codex review on `ed7fd3b`
(`1fee685` fixed the other three: `global`, PEP 613 `TypeAlias`, PEP 695 type
parameters). Independently reproduced against `1fee685` before being fixed.

**Conditional-branch shadowing evaded detection.** `if False: Literal = str`
followed by `RunStatus = Literal[...]` erased the `Literal` binding for the
rest of the scope even though the branch never runs, since `_scope_nodes`
walks every branch of an `if`/`try`/`while`/`for`/`with` as though it always
executes -- real control flow decides which one, if any, actually does.

Fix: `_scope_nodes` now tags each node with whether it is only reachable
through such a construct. A new `_rebind` helper applies a binding as before
in every unconditional case, but inside a conditional construct it refuses
to let a plain, non-typing value silently replace an already-meaningful
typing form or import -- the branch that keeps the meaningful binding could
be the one that actually runs at runtime. It does not block a conditional
rebinding to a *different* meaningful form (e.g. re-importing under a
different name in each branch of a version-guarded import): only a
downgrade to a plain value is protected. The common `try: from typing
import TypeAlias except ImportError: from typing_extensions import
TypeAlias` fallback -- itself conditional -- still resolves correctly, and
an unconditional (non-branch) rebinding still erases the prior meaning
exactly as before.

All 175 tests across the seven published lifecycle suites plus this file
pass. Reverting only the scanner (keeping this test file) makes exactly the
one new branch-shadowing case fail; the three sanity cases in the same file
(legitimate try/except fallback, conditional rebind to another meaningful
form, unconditional rebind still erasing) all pass either way, confirming
the guard is scoped to the one demonstrated gap. `ruff check`/`ruff format
--check` are clean, and the real-repository gate still reports 19 classified
work-state vocabularies with no new unauthorized debt.

The fifth finding -- `_discover_at_revision`'s trusted-base lookup using the
head-tree path, which misreports a module that moved/restructured between
base and candidate as newly added -- remains deferred. Fixing it needs a
revision-aware module/path mapping instead of reusing
`_collect_modules()`'s head-tree view (itself a filesystem-glob walk coupled
to the working tree, not easily made revision-aware without checking out
the base revision), which is a larger, separate piece of work.

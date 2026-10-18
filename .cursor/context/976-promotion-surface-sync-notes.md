# Lane L976 round notes — develop sync, import cycle fix, promotion-surface red

Branch `auto-976`, round starting at head `4a2140c58` (issue #976, M9-I1).

## What this round did

1. **Resolved the preserved develop-sync conflict.** The worktree carried an
   in-progress merge of develop `420d503d` with 3 conflicted files
   (CHANGELOG.md, `extensions/__init__.py`, `cli/_extensions.py`) — both-adds
   conflicts, resolved as unions (`dd06f3804`). Then merged the remaining 2
   develop commits up to `35a72ff` (`c784df6d4`, clean auto-merge).
   `quality/` verified byte-identical to `origin/develop` via
   `git diff --numstat origin/develop -- quality/`.

2. **Fixed a real import cycle the sync exposed** (commit of this file):
   develop's `maistro/extensions/__init__.py` now imports
   `.isolation` → `sandbox → runs → graph → harness_executor`, which imports
   `maistro.capabilities` — so #976's module-level
   `from maistro.extensions.attribution import ...` in
   `capabilities/governed_invocation.py` and
   `capabilities/provider_adapters.py` re-entered partially-initialized
   `maistro.capabilities` (manifest: `test_metering.py::
   test_two_os_processes_cannot_race_same_remaining_budget` ImportError).
   Fix: both imports moved to function scope (walker-visible, semantics
   unchanged). All suites pass post-fix.

## OPEN BLOCKER for the next lane (needs a decision above implementation-lane authority)

`python3 scripts/check-promotion-surface.py` (CI job "Every module the
promotion path reaches escalates", ci.yml:250) is RED on this branch:

- On `origin/develop` (`35a72ff`): exit 0, closure 272 modules, no
  `maistro.extensions` in the closure.
- On pre-merge `4a2140c58`: exit 1 with 13 flagged modules (all core
  `maistro.extensions.*`) — i.e. the red predates this sync; the prior round
  never ran this gate.
- On the merged tree: exit 1 with 355 flagged modules. The RSI closure
  reaches `maistro.capabilities.providers.llm_gateway` → `provider_adapters`
  → (`extensions.attribution`, `extensions.semver`) and `governed_invocation`
  → `extensions.attribution`; importing any `maistro.extensions.*` submodule
  pulls the package `__init__`, which (post-develop-merge) imports
  isolation/sandbox/runs/graph — exploding the closure to 661 modules.

The walker (`ast.walk`) deliberately counts function-level imports, so lazy
imports do not evade it; the coupling is real (#976 capability dispatch
genuinely loads extension identity code).

Repair options, all outside this lane's authority:
- baseline rows in `quality/promotion-surface-baseline.json` (~355, or 13 on a
  decoupled design) — a ledger edit requiring the two-merge authorization
  workflow (grant must land from the merge base first);
- protection patterns in `maistro_rsi/sensitive_paths.py` — a policy change;
- architectural decoupling of `maistro.capabilities` from
  `maistro.extensions` (e.g. decoding attribution at bootstrap time instead
  of invocation time) — an accepted-design change that would churn #976's
  pinned tests.

## Re-validated after the sync (all green)

ruff check/format; mypy (CI's 10-package list, 1062 files); extensions +
capabilities suites (1852 passed, 7 skipped); maistro-server (565 passed);
vulture/radon/reachability/dispositions/promotion-input ratchets with CI args
(1322==1322); suite inventory (17 suites ok); test-duplicates;
cross-package-imports; extension-imports; dependency-namespaces;
release-consistency; doc-links; contract-markers; backlog-consistency.
Only promotion-surface is red (see above).

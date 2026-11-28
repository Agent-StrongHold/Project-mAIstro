---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# Issue #7: the #492 JIT provisioner consumes the retiring users store only through the registry

CI on the lane head red `Quality / Workspace retirement`:
`packages/hive-conductor/backend/stores.py::users` is a RETIRE row whose
importer list only shrinks, and the new `services/entra_jit.py` bound `stores`
directly for its lost-link-race recovery lookup. The repair routes that lookup
through `UsernameRegistry.get_user` (new public form of `_durable_user`, plus
the module-level delegate) — `username_registry` is already a recorded
importer — and drops the module's `import stores`.

Two tests join `TestConcurrentLinkRace`:

1. A structural pin: `services.entra_jit` must not bind the retiring `stores`
   module. It failed against the pre-repair module (which bound `stores`) and
   passes after the repair; the CI ratchet it mirrors runs only in
   quality.yml, while this suite runs in every backend producer.
2. A durable-race case: the recovery returns the canonical account from a real
   `PersistedStore` backend when the account exists only durably, proving the
   registry seam (`get_user` -> `_durable_user` -> backend `get`) the
   provisioner now depends on. Its docstring records why this case alone is
   not the regression discriminator: allocation itself hydrates the users
   table into memory, masking a memory-only read; the structural pin above is
   the guard.

Focused suites: JIT 41 passed; `test_username_registry.py` +
`test_registration_policy.py` 81 passed. Complete backend suite: 4573 passed,
113 skipped. `check-workspace-retirement.py` (CI arguments,
`RATCHET_BASE_REV=origin/develop`): OK, 89 entries match the tree, 78 -> 78
tolerated importers — no ledger edit. This is a bounded CI-gate repair for the
#492 slice; milestone #7 acceptance is otherwise unchanged (see
`docs/implementation/issue-7-handoff.md`).

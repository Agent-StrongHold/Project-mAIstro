---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 937 activation-lock concurrency (post-install lifecycle)

Salvage continuation of the #954 post-install extension lifecycle lane under
initiative #937 (epic #939): concurrent installs of one extension could each
observe the same prior ACTIVE record, both take the scope's pointer, and each
supersede only that shared prior — leaving the losing install ACTIVE under a
pointer naming the winner.

## Changed files

`packages/maistro-core/src/maistro/extensions/service.py` adds a per-
`(scope, extension)` activation lock serializing every read-modify-write of
the active pointer: install's pin fence → pointer swap → supersede, enable's
version-move refusal check, and rollback's restore. The lock is always
acquired after the per-record lock(s) (install/enable take the record lock at
the public entry point; rollback takes both sorted record locks first) and no
record lock is acquired while holding it (`_transition` is lock-free), so the
lock order is acyclic — a rollback racing an install in the opposite
direction cannot deadlock.

`packages/maistro-core/tests/extensions/test_post_install_lifecycle.py` adds
1 node ID:

- `TestConcurrentActivation::test_concurrent_installs_of_one_extension_leave_exactly_one_active`
  races two separately authorized installs of the same scoped extension,
  yielding inside the store's `active_record`/`set_active` to open exactly the
  window where both racers capture the same prior. Asserts exactly one ACTIVE
  record per (scope, extension), that it is the one the pointer names, and
  that the loser is SUPERSEDED. Verified to fail against the pre-lock service
  (loser left ACTIVE) and pass with the activation lock.

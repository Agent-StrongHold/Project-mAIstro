---
inventory-delta:
  tests/: +4
---
# claude-ac-state-shim-surface-4d1c

`tests/test_check_ac_state.py` (+4, in place). Nothing moved or was deleted, and
the five tests that were failing on `develop` are unchanged — they were correct
and are now passing again, which is the point.

The four new ones state the property those five were reporting indirectly, so a
future re-split cannot reintroduce it quietly:

- **a patch on the entry point reaches the implementation** — the claim;
- **reads fall through** — a proxy that only forwarded writes would leave every
  read on a stale copy;
- **a name the entry point owns is not pushed down** — `main` exists on both,
  and the entry point's *is* the merge guard, so a proxy forwarding every write
  would replace the implementation's `main` with the guard and recurse;
- **an unknown name is still an `AttributeError`** — a proxy that answered
  everything would satisfy the first three while making every typo silent.

Mutation-verified in both directions: removing the write proxy fails the first,
and forwarding *every* write fails the third. Restoring the original
copy-into-globals loop fails the five original tests and nothing else, which is
what identifies this as their cause rather than a coincidence.

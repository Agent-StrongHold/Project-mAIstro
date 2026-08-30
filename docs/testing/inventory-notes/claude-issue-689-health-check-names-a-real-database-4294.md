---
inventory-delta:
  tests/: +8
---
# claude-issue-689-health-check-names-a-real-database-4294

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

All 8 are added, none removed: one new file,
`tests/test_postgres_health_checks.py`.

Six are one parametrized case per PostgreSQL service the workflows declare —
the gate itself, asserting each `pg_isready` probe names a database its own
container creates. It is a test rather than a one-time correction because the
correction is one string per service block and nothing else would notice it
coming back; #682 introduced the defect that way, and #689 is the result.

The seventh refuses an empty parametrization. A guard that silently matches
nothing is not a guard, and this one is only as good as its discovery.

The eighth guards the parse, and it exists because the first version of this
file was **vacuous**. `--health-cmd "pg_isready -U maistro"` has two levels of
quoting: `shlex.split` returns the whole command as one token, so a scan for
`-U` found nothing, every service fell back to the always-present `postgres`
default, and all six cases passed against a deliberately reverted probe. Caught
by mutation-checking rather than by reading. The eighth test pins the split and
both readings of the defect, so the same mistake cannot make the other six pass
for the wrong reason again.

Nothing in `packages/` moved; this change is four workflow strings and the test
that keeps them honest.

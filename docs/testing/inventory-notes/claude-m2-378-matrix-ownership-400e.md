---
inventory-delta:
  tests/: +23
---
# claude-m2-378-matrix-ownership-400e

The Convergence Matrix checker verified reachability *counts* and left the
sentence beside them unchecked, so a row could name a current owner that no
product path reaches. Fifteen did — `builders.runtime`, `tools.approval`,
`projects.authorization`, `canvas.store` and eleven more — and the matrix read
as though each were wired. That is the one claim an "who owns this today"
column must not get wrong.

**`tests/test_check_convergence_matrix.py` (+23)**, in four groups:

- **One test per owner column.** A lifecycle, a persistence and an
  authorization owner that nothing reaches each fail on their own. Separate
  tests rather than one parametrised case because the failure has to name the
  column: a checker reading the wrong cell would pass a single combined test.
- **Annotations, in both directions.** `(unreachable)` licenses a claim the
  import graph cannot back; the same annotation left on a module that *is*
  wired fails too. A one-directional check would let the annotations rot into
  exactly the stale prose they were added to replace. `(planned)` is not a
  claim about today and is refused on a `KEEP` row; `(delegated)` is how a row
  says it reads another subsystem's owner, and without it two rows claiming one
  lifecycle record fails.
- **Resolution.** Cells abbreviate — `runs.pg_store` for
  `maistro.runs.pg_store`, `design.engine` for `maistro_design.engine` — so a
  name is resolved against the row's own module prefixes first. A name that
  resolves to nothing fails, and so does one that resolves to two modules,
  which would otherwise leave the reader guessing which owner was meant.
- **The residue.** A cell may describe a non-module owner in prose ("OS file
  permissions", "per-route"); those are accepted and counted, not rejected,
  because rejecting them would push a writer toward a plausible module name.
  The count is checked, so a stale census fails — the stated limitation cannot
  drift the way the ownership prose did.

Four more tests cover ground the ownership work moved rather than added: rows
present in only the disposition table, the two tables listing the same rows in
a different order, a missing census marker, and an ownership table that dropped
an owner column. The first two were untested branches that this change relocated
into `_key_failures`; leaving them uncovered would have banked someone else's
gap as mine.

The census helper in the test file classifies cells by hand rather than calling
the gate's own classifier. A helper that reused the code under test would make
the census assertion agree with itself no matter what the code did.

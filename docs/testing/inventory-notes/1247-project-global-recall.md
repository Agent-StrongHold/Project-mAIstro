---
inventory-delta:
  packages/maistro-core/tests: +21
---
# 1247-project-global-recall

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

## Source of the +21

`test_project_global_recall.py` adds seven cases for each of memory, SQLite and
PostgreSQL: three direct caller-organization cases; three real Layer 3 cases;
and one deduplication/ranking/limit regression. This is 7 × 3 = 21 collected
node IDs, with no existing test removed or renamed.

At base `aac5457cc642914cf550b3fce3257f87b73dacd3`, the new memory/SQLite cases
show ten failures. The original #1639 store guards reduce that to six failures:
Layer 3 still loses authorized same-org GLOBAL wisdom. The completed correction
passes all fourteen memory/SQLite cases, preserving project-only AGENT/USER/TEAM
history and public GLOBAL visibility. The seven PostgreSQL cases require a real
`MAISTRO_TEST_PG_DSN`; a local skip is not PostgreSQL passing evidence.

The SQL stores compile GLOBAL visibility through the existing `scope_predicate`;
Python uses `matches_scope`. Layer 3 combines two bounded existing store reads,
then deduplicates by ID, sorts by weight and ID, and applies the requested limit.
No new scope, store protocol, baseline allowance or sharing authority is added.

## Preserved earlier work

The repair merge retains original PR #1639 head
`dcb905dafc1b386fbc036614d09cea674f1eee22` as an ancestor, including its
`test_unscoped_global_recall.py` regression and separate +1 inventory note.
The resulting complete core-suite inventory is 12091, not 12090.

The fleet's read-only report also recovered an unpublished, spec-only commit
`c154bca217bbf2ab3797e53ac0cfc0885d9a9431`, parent `dcb905daf`, authored by
Blake Matthews on 2026-09-28 at 00:04 UTC. Its SPEC-244 correction exempted
only non-global project rows from hierarchy filtering and retained the
org-bound GLOBAL check. The updated normative paragraph preserves that
correction, explicitly preserves truly unbound GLOBAL visibility, and adds
the same-org Layer 3 behavior absent from that spec-only patch. That local
fleet branch was neither overwritten nor published by this repair.

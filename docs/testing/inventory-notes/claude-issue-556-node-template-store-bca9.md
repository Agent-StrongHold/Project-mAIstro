---
inventory-delta:
  packages/maistro-core/tests: +63
---
# claude-issue-556-node-template-store-bca9

Two files, both under `packages/maistro-core/tests/graph/`. Nothing was moved,
renamed, split or deleted, so the number is not hiding a compensating change.

`test_node_template_store.py` is the bulk: 14 bodies parametrised over three
backends — the in-memory reference, SQLite and PostgreSQL — for 42 node IDs.
The reference is inside this suite rather than beside it, for the reason #522's
workspace conformance suite records: it *is* the definition of the contract, so
running the same bodies against it and against the two durable stores makes
"the durable ones behave like the reference" a comparison rather than a claim.
Two of the fourteen carry `@pytest.mark.ac` — AC-12 (provenance resolves
identically after a reopen) and AC-7 (publishing a version leaves the previous
one addressable and byte-identical).

The remaining 9 are three bodies added to the existing `test_template_store.py`,
over the same three backends: `TestContentIsValidatedWhereItBecomesARecord`.
Those cover the deferred P1 from #555 — a template validated at construction can
be mutated into an invalid one before it is stored, because every content field
is a mutable `dict` or `list` and no validator runs on in-place mutation.

**Counted with a PostgreSQL server present.** The PostgreSQL legs are collected
either way — `pytest.skip` happens at run time, not collection — so the node-id
count is the same with and without a server, and this number does not move when
the `postgres` job runs the same files with `MAISTRO_REQUIRE_PG_LEGS=1`.

Verified against the pre-fix code: removing `revalidated()` from the three
`put()` implementations fails 6 of the 9 — the two refusal bodies on all three
backends — and leaves the third passing, which is correct, since it is the
control asserting an unmutated template still stores.

## Plus 3, from a branch CI could see was unrun

The diff-coverage gate named `runs/wiring.py` at 81.2% — uncovered lines 94,
96 and 102, which are the whole fallback half of `_pg_node_template_store`:
the case where a PostgreSQL pool's database is migrated to 018 but not 019.
Written and never executed, that branch was a comment with a syntax, which is
the same gap this gate found in #522's purge bound.

Three bodies in `tests/runs/test_wiring.py`, mirroring the ones `schedules`
already has: the fallback returns a working in-process registry and warns how
to fix it; a migrated pool gets the durable store and is NOT told to migrate;
and `node_templates` is absent from `SPINE_PG_TABLES`, asserted because the
tempting fix for a future "why aren't my NodeTemplates durable" is to add it
there, and that fix would drop every pre-019 deployment to an in-memory spine.

## Plus 9, from Codex review

Three new bodies over three backends. Each was written after a finding, and
each was checked against the pre-fix code before being kept.

- `test_two_concurrent_publishers_cannot_both_win` — the SQLite conflict check
  was a read then a write across an `await`, so two coroutines could both see
  no row and the second silently overwrite the first. Exactly one publisher
  must win and the other must raise.
- `test_re_registering_under_another_workspace_moves_every_column` — the
  content hash excludes `workspace_id`, so identical content under a different
  Workspace matched PostgreSQL's upsert predicate and updated the payload
  alone. `get` reported the new Workspace, `list_for_workspace` the old one.
  Reverting the fix fails this on the `postgres` leg only, which is the shape
  of the defect.
- `test_the_reference_keeps_provenance_within_one_process` — the in-memory
  half of AC-12's property. It cannot answer the criterion (no reopen) so it
  carries no marker, but leaving it untested would drop the reference out of
  the comparison the durable stores are measured against.

`test_provenance_resolves_identically_after_a_reopen` was rewritten rather than
added to, and its node-id count is unchanged. It held one store instance and
called `get()` on it, which proves nothing about a restart — the in-memory leg
loses everything and the SQLite leg kept the same connection open. It now
registers through one store, drops it, and reads through a second over the same
database; the in-memory leg skips, because there is no restart for it to
survive. Verified: breaking the SQLite `put`'s commit fails it, where the old
version passed.

The SQLite fixture moved from `:memory:` to a file for that reason — a
`:memory:` database lives inside its connection, so "open a second store" would
have meant "open an empty one", and the reload test would have passed for the
wrong reason on one backend while failing on the other.

---
inventory-delta:
  packages/maistro-core/tests: +51
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

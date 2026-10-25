---
inventory-delta:
  packages/maistro-core/tests: +6
---

# Authority cutover ledger, proof, and reversibility (#102)

`packages/maistro-core/tests/backlog/test_authority_cutover.py` is new: 6
node IDs for `maistro.backlog.cutover`. The ledger defaults to markdown
authority, records every flip with revision/actor/note, and reverting
appends (never deletes) so history survives validation-time reverts. The
SQLite control store (`backlog_authority` + `backlog_documents`) is proven
across a restart — new connections read what a closed connection wrote, and
the persisted token stream replays identically. `cutover_to_db` refuses to
flip unless the export reproduces the document byte-for-byte (guard exercised
directly), and the post-cutover `export_authoritative` regenerates identical
bytes from the database alone after a restart, appending post-cutover items
under the generated heading deterministically. No existing test was removed
or renamed.

---
inventory-delta:
  packages/maistro-core/tests: +7
---
# 102-backlog-cli-entry-point

CI-repair round for the #102 branch: the operator cutover tool moved from
`scripts/backlog_cutover.py` into the shipped CLI as `maistro backlog`
(`maistro.cli._backlog`), which is what makes the `maistro.backlog.*` modules
reachable from a real process entry point (the reachability ratchet demands
this and forbids the branch from banking the unreachable rows without a
trusted-base grant). The new suite `packages/maistro-core/tests/backlog/
test_backlog_cli.py` pins the CLI-specific contract in 7 node IDs: the file
projections of a cutover (banner, export digest, authority marker), the
idempotent import, the refused `generate` under markdown authority, the
revert restoring the hand-maintained document, and the agent verbs
(list/select/claim/write/release) with their fail-closed no-role behavior.
The domain behavior underneath stays pinned by the existing backlog suites
(test_markdown_migration, test_authority_cutover, test_agent_surface,
test_backlog_store_conformance — unchanged). No test was removed or skipped.

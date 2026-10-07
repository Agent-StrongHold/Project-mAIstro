---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# 886 M8-A6: Workspace noninterference harness (+15)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #886 (epic #880) asked for a prototype noninterference harness: operations
scoped to Workspace A must leave untouched Workspace B's observable state
unchanged, modulo documented global state. The research record
(`docs/research/886-workspace-noninterference.md`) registers **WATCH** — zero
live isolation defects found at this head, with the oracle validated by two
injected-and-reverted mutation classes — and this change lands the harness as
one self-contained test module in `packages/hive-conductor/backend/tests/`
(`test_m8a6_workspace_noninterference_research.py`, +15 node IDs).

Unlike the maistro-import-free M8-B2 harness, this one runs against the real
implementation by the issue's own requirement: two fresh principals create two
real Workspaces through the product HTTP API, alice operates A across 19
operation families (workspace archive/recover, members, schedules, agents,
memory, chat sessions, feedback, queries, store re-initialization; the 64-step
seeded sequence ends by deleting A), and bob's normalized projection of B —
HTTP views plus the canonical/membership/Root-Project/presentation store rows,
timestamps included — is asserted unchanged after every step. Anti-vacuous
guards: fixed-seed coverage of every vocabulary entry, a mutation ledger,
projection reads that fail loudly on degradation, and sensitivity controls that
prove a B-side write changes the projection. The other 14 cases: baseline
independence, per-family attribution (8 parametrized), delete-cascade
containment, A-side visibility, the persona-feedback cross-workspace exception
(store level; the API summary is admin-gated), the chat lazy-seed false-positive
source, and the two sensitivity controls.

No product code, no flag, no authority path touched; the module only reads the
seats the product already exposes, so no vulture/reachability identity changes.

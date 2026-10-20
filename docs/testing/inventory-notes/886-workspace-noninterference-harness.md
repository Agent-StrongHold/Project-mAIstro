---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
---
# 886 M8-A6: Workspace noninterference harness (+17)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #886 (epic #880) asked for a prototype noninterference harness: operations
scoped to Workspace A must leave untouched Workspace B's observable state
unchanged, modulo documented global state. The research record
(`docs/research/886-workspace-noninterference.md`) registers **WATCH** — zero
live isolation defects found at this head, with the oracle validated by two
injected-and-reverted mutation classes — and this change lands the harness as
one self-contained test module in `packages/hive-conductor/backend/tests/`
(`test_m8a6_workspace_noninterference_research.py`, +17 node IDs).

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
prove a B-side write changes the projection. The other 16 cases: baseline
independence, per-family attribution (8 parametrized), delete-cascade
containment, A-side visibility, the persona-feedback cross-workspace exception
(store level, now also asserting the middleware admin gate that refuses a
non-admin GET on the summary path), the chat lazy-seed false-positive source,
the two sensitivity controls, a same-principal two-Workspace case (review P2:
Alice holds an editor membership in Bob's B and seeds a B-side schedule through
it, so a regression that keeps principal isolation but drops Workspace
isolation — deleting every schedule owned by the acting *user* — changes B's
projection and fails the oracle; the simulated user-scoped delete is embedded
as a sensitivity leg), and a matching-persona delete-cascade case (review P2:
Bob owns a second Workspace C instantiating A's persona, so a faulty cascade
that deletes Agents by `persona_template_id` rather than `workspace_id` is
caught, with the persona-scoped wipe simulated as a sensitivity leg).

No product code, no flag, no authority path touched; the module only reads the
seats the product already exposes, so no vulture/reachability identity changes.

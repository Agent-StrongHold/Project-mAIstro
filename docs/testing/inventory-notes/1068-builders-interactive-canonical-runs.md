---
# Issue #1068 Builders interactive canonical execution

Issue: #1068
Parent: #49

inventory-delta:
  packages/maistro-core/src/maistro/builders/interactive.py: +1
  packages/maistro-core/tests/builders/test_interactive_execution.py: +3
  packages/maistro-core/tests/cli/test_builders.py: +1 architecture guard
  packages/maistro-core/src/maistro/cli/_builders_tui.py: wired shipped producer
  packages/maistro-core/src/maistro/cli/_builders_sessions.py: persisted canonical IDs
---

## Claim and collision boundary

The shipped `maistro builders` TUI remains the product entry point and keeps
SPEC-201's ReAct `TurnRunner` as its domain strategy. The new adapter admits
one bounded interactive turn as a canonical Graph/Run and executes the ReAct
strategy as the physical work of its NodeRun/Attempt. No Builders-private Run
store, scheduler, authorization path, or effect provider is introduced.

The CLI uses the existing `wire_execution_spine` backend selection. With no
configured deployment database it uses the CLI's private SQLite scope at
`~/.maistro/builders.db`; configured SQLite/PostgreSQL URLs use the same
canonical stores and inspection identity. Session history stores the exact
canonical `run_id` values rather than treating the local session ID as an
execution identity.

## Evidence

`test_react_turn_is_admitted_as_one_canonical_run_and_physical_attempt` proves
one interactive turn creates a scoped canonical Run, one Builders NodeRun and
one completed Attempt. The failure test proves the ReAct `max_turns` failure
settles the canonical Run and Attempt as failed rather than returning success.

Cancellation remains owned by `run_durable_graph`: its cancellation handler
settles open physical work and the canonical Run before propagating the task
cancellation to Textual.

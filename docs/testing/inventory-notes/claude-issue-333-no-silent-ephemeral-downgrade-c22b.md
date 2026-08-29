---
inventory-delta:
  packages/hive-conductor/backend/tests: +28
---
# claude-issue-333-no-silent-ephemeral-downgrade-c22b

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_state_durability_mode.py` — 28 tests for SPEC-082926-87bb (#333).

Twenty-two test functions; three are parametrised (unset modes, unrecognised
modes, case and whitespace), which is why the node count is higher.

Two of the twenty-two exist because the diff-coverage gate found real gaps: the
`StoreUnavailableError` handler in `main.py` was never reached by the first
settings test (that 503 came from the route's own catch, not the handler), and
`/health`'s defensive fallbacks had no case at all.

One existing test was **rewritten rather than added to**:
`test_foundation.py::test_init_state_exception_falls_back_to_in_memory` asserted
the fallback that this issue exists to remove. It is now
`test_init_state_exception_degrades_rather_than_falling_back` and asserts the
recorded status instead. Same seam, opposite claim — the old assertion was a
test of the defect.

The four causes #333 names are each injected at the seam they really enter
through, not simulated one layer up: an unwritable path is a directory where
`state.db` should be (no stubbing at all), a failed migration is a real
`MigrationFailedError` from `PersistedStore.initialize`, a missing import is a
module whose `__getattr__` raises, and a mid-load outage is a `list_all` that
fails after two stores have already loaded. Collapsing them into one fake would
reproduce the defect being fixed, which was that all four came out of one
`except` indistinguishable.


The count above includes #334's suite merged forward: this branch is stacked on
`claude/issue-334-durable-conductor-settings`, so its 41 settings-durability
tests land here too until #599 merges and the base retargets to `develop`.

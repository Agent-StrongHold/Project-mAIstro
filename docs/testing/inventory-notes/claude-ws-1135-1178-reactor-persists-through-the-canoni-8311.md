---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +6
---
# claude-ws-1135-1178-reactor-persists-through-the-canoni-8311

#1135 / #1178: the Reactor now persists through the owning `State` writer.

- `packages/maistro-core/tests` (+6): `tests/reactor/test_reactor.py` replaces
  the single `test_handler_uses_state_submit` (which exercised the removed
  private raw-sqlite writer) with seven tests: writes land through a shared
  `State` and `reactor_log_001` is a State migration; `state_submit` calls
  `State.submit`; forced interleaving with `PersistedStore.put` never locks;
  a restarted `State`/`Reactor` reads the same rows; no-State behaviour; the
  `state=` + `state_db_path=` combination is refused; the deprecated
  `state_db_path=` owns one State and closes it on stop.
- `packages/hive-conductor/backend/tests` (+3): new
  `test_foundation_reactor_state.py` starts a real Foundation with a custom
  `CONDUCTOR_STATE_DB` and checks rows land there (no `data_dir/state.db`),
  interleaved Reactor + PersistedStore writes, and restart read-back.

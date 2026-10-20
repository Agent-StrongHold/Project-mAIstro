---
inventory-delta:
  packages/maistro-server/tests: +1
---

# #1057 CI repair — cover the shutdown ImportError branch the diff gate named

The lane's CI `Coverage gate (publish-set floor + diff coverage)` job
(actions/runs/36304686281, job 108584171202) failed on exactly one file:

    packages/maistro-server/src/maistro_server/main.py:
      60.0% of 5 changed lines (need 90%); uncovered 396, 397

Those two lines are the `except ImportError: pass` half of the lazy sandbox
cleanup import that the earlier lean-import repair
(`1057-lean-app-import-surface.md`) added to the lifespan's shutdown path.
The existing `TestLifespan` tests patch
`maistro.tools.sandbox.server.cleanup_all_containers` directly, which imports
the real module — so the happy path (import succeeds, `await` runs) was
covered, but the missing-`[llm]`-extra branch that the comment documents as
the *point* of the change was never executed by any suite.

**+1 `packages/maistro-server/tests/api/test_main.py`**:

- `TestLifespan::test_shutdown_survives_a_missing_sandbox_extra` — installs
  `None` in `sys.modules` for `maistro.tools.sandbox.server`, which makes the
  shutdown-time `from ... import cleanup_all_containers` raise ImportError
  deterministically even in the full-extras CI interpreter, then asserts the
  lifespan still stops the runner and reaches the final
  `maistro_engine_stopped` log. This exercises main.py:396-397 (the branch)
  and its arcs; nothing else in the app graph imports that module, verified
  by grep over `maistro-core`/`maistro-server` sources, so the block cannot
  disturb startup.

Validation on this head: maistro-server suite under the gate's own producer
command (`coverage run --branch --source=.../maistro_server -m pytest
packages/maistro-server/tests`): 409 passed, and `main.py` reports 100% lines
and branches (394/395/396/397/399 all executed). Suite inventory gate green.

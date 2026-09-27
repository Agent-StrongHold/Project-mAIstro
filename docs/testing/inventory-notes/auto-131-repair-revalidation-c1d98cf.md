# auto-131 repair round: re-validation at c1d98cf72 (job f6726e80)

Verification-only round: no test inventory change, so no `inventory-delta:`
block. The two carried findings were re-derived and re-executed against this
head (which adds the develop merge `8bb344e32` on top of the earlier
revalidation `3d2dc0347`), not trusted from the prior round.

Both findings cite line numbers from the tree at `1a9b8037d^`; the fix commit
`1a9b8037d` ("fix(chat): continue retention past protected parents") is an
ancestor of this head, and both findings remain stale at it.

1. Retention past a protected parent (finding 1): the exact
   `max_retained=2` scenario was re-executed out-of-tree at this head —
   terminal chat parent holding a terminal child, a second terminal turn,
   then a third admission. Result: no `RunIntegrityError` escapes,
   `window=2` (== bound), the younger terminal Run is deleted, the protected
   parent and the new CREATED Run remain. The declared bound is enforced.
2. Coverage (finding 2):
   `packages/maistro-core/tests/runs/test_chat_admission.py::test_retention_walks_past_a_terminal_parent_with_a_child`
   executes that scenario directly and passes at this head.

Durable-store parity re-checked by reading `pg_store.delete_run`
(packages/maistro-core/src/maistro/runs/pg_store.py:504): it raises the same
`RunIntegrityError` for non-terminal and children-present cases, so the
sweep's catch-and-continue contract holds on the Postgres store as well.

Executed at this head:

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py` — 30 passed.
- `pytest packages/maistro-core/tests/runs/test_chat_retention_sweep.py
  packages/maistro-core/tests/runs/test_chat_execution.py
  packages/maistro-core/tests/runs/test_chat_attempt_recovery.py
  packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-core/tests/integration/test_chat_to_graph_e2e.py`
  — 132 passed / 4 skipped (with admission above: 162 total).
- `pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py` — 40 passed
  (incl. end-to-end session correlation through the HTTP seam and the
  additive `choices` + `run_id` OpenAI shape).
- `pytest packages/maistro-core/tests/runs -q` — 862 passed / 203 skipped.
- `ruff check` and `ruff format --check` on the chat admission module and its
  tests — clean.

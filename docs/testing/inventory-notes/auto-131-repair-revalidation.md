# auto-131 repair round: re-validation at 0b5211f00 (job d6169dda)

Verification-only round: no test inventory change, so no `inventory-delta:`
block. Both prior findings were re-derived and re-executed at the current head
(develop e15706ced merged into the lane), not trusted from the prior job.

1. Retention past a protected parent (prior finding 1): reproduced both ways
   out-of-tree. With `ChatRunAdmitter._sweep`'s `RunIntegrityError` catch
   neutralised (module attribute rebound to an unrelated class so the except
   no longer matches), the exact `max_retained=2` scenario — terminal chat
   parent holding a terminal child, then a second terminal turn, then a third
   admission — raises `RunIntegrityError` out of `admit()` and strands
   `window=3 / chat_in_store=3` against a declared bound of 2. With the
   shipped catch, the same scenario yields `window=2 / chat_in_store=2`, the
   younger terminal Run deleted, the child-protected parent preserved, and the
   third Run CREATED. The catch is load-bearing; the bound is enforced.
2. Coverage (prior finding 2):
   `packages/maistro-core/tests/runs/test_chat_admission.py::test_retention_walks_past_a_terminal_parent_with_a_child`
   executes that scenario directly.

Executed at this head:

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py` — 30 passed.
- `pytest packages/maistro-core/tests/test_container_chat_runs.py` — 33 passed.
- `pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py` — 38 passed
  (incl. `test_a_turn_yields_a_run_id_that_resolves`: response `run_id`
  resolves in the store with `CHAT_SOURCE` + `session_id` + `request_id`
  provenance, terminal COMPLETED; streaming twin agrees via the
  `X-Maistro-Run-Id` header and both chunks).
- `pytest packages/maistro-core/tests/runs -q` — 850 passed / 202 skipped.
- `pytest packages/maistro-server/tests/api -q` — 352 passed.
- `ruff check .` clean; `ruff format --check .` clean.
- `scripts/check-execution-lifecycles.py`, `scripts/check-adr-index.py`,
  `scripts/check-adr-status-language.py`, `scripts/verify-monorepo-layout.sh`
  — all OK.

Repaired this round: `check-suite-inventory.py` failed on this lane's own
note `auto-131-merge-resolution.md` — its `inventory-delta:` block held
`added: []` / `removed: []`, which `DELTA_LINE_RE` cannot read, and the gate
refuses an unreadable delta rather than silently zeroing it (the note's
previous claim that the gate was OK was false at this head). Fixed by
removing the block per the gate's contract for a no-change note and moving
the explanation into prose. The gate now passes all 13 suites
(`packages/maistro-core/tests` 10631, `packages/maistro-server/tests` 365, …),
which also re-confirms the +1/+2 deltas this lane's other notes declare.

Residual, recorded rather than hidden: the lane does not yet carry
origin/develop's two newest commits (f695d491f governed model egress wiring,
5f7088dd evolve admission provenance stamp). Neither touches the chat
admission surfaces this issue owns, and the full core-runs and server-api
suites pass without them; the integration merge belongs to the driver.

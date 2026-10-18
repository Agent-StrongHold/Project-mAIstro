# auto-131 repair round: re-validation at e1af5d2c5 (job c3b187ea)

Verification-only round: no test inventory change, so no `inventory-delta:`
block. The driver's two findings were re-derived and re-executed against this
head, not trusted from the prior (rate-limited, unfinished) job.

Both findings cite line numbers that match the tree at `1a9b8037d^`; the fix
commit `1a9b8037d` ("fix(chat): continue retention past protected parents") is
an ancestor of this head, and both findings are stale at it.

1. Retention past a protected parent (finding 1): the exact `max_retained=2`
   scenario was re-executed out-of-tree at this head — terminal chat parent
   holding a terminal child, a second terminal turn, then a third admission.
   Result: no `RunIntegrityError` escapes, `window=2` (== bound),
   `chat_in_store=3` is the protected parent + its child + the new Run, the
   younger terminal Run is deleted, the third Run is CREATED. The declared
   bound is enforced.
2. Coverage (finding 2):
   `packages/maistro-core/tests/runs/test_chat_admission.py::test_retention_walks_past_a_terminal_parent_with_a_child`
   executes that scenario directly and passes at this head.

Executed at this head:

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py` — 30 passed.
- `pytest packages/maistro-core/tests/test_container_chat_runs.py` — 33 passed.
- `pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py` — 40 passed
  (incl. end-to-end session correlation: gate test asserts
  `run.provenance["session_id"] == "session-chat-1"` through the HTTP seam).
- `pytest packages/maistro-core/tests/runs -q` — 850 passed / 202 skipped.
- `pytest packages/maistro-server/tests/api -q` — 356 passed.
- `ruff check .` clean; `ruff format --check .` clean.
- `scripts/check-execution-lifecycles.py` (19 vocabularies OK),
  `scripts/check-adr-index.py` OK, `scripts/check-adr-status-language.py` OK,
  `scripts/check-suite-inventory.py` (13 suites OK),
  `scripts/verify-monorepo-layout.sh` OK.

Acceptance evidence at this head: `run_id` on the chat response resolves
through `/v1/runs/{run_id}/node-runs` with a completed NodeRun;
granularity (one Run per turn) and retention (admitter window of
`MAX_RETAINED_CHAT_RUNS`, source-aware store bound, restart gap named for
#132) are recorded in ADR-082326-c126; the bound has direct tests plus the
reproduction above; existing chat behaviour has parity coverage across status
mapping, model echo, streaming and gate tests.

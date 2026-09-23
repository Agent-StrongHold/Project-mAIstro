# auto-147: bank the measured AC-state bound (repair of the required-gate finding)

Repairs the one blocking finding from the verification at merge head `a02a455574`:
`scripts/check-ac-state.py --run-tests --ratchet --mandate 8bb344e32` (required check,
`.github/workflows/quality.yml:951-955`) exited 1 with `FAIL: unbanked improvement` —
design coverage measured 37.693% against the folded floor 36.5259%, and the branch had
never banked its own head measurement.

No tests were added, moved or removed by this change: every suite count in the ledger is
untouched.

## What was executed

- Reproduced the finding at head `f254aeaf6` in the CI shape (dedicated pgvector:pg18
  container, `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set, `uv run alembic upgrade head`
  applied first — mirroring the workflow's "Apply migrations" step): exit 1,
  `FAIL: unbanked improvement — design_coverage: 37.693, floor still says 36.5259`;
  acceptance mandate OK (0 unproven touched criteria) and chain mandate OK
  (0 absent links); `'Implemented', contradicted: 0` — the earlier
  "4 contradicted Implemented specs" observation does not reproduce at this head.
- Banked with the same CI shape: `uv run python scripts/check-ac-state.py --run-tests
  --ratchet --bank` → wrote `quality/ac-state-notes/auto-147.json`
  (`design_coverage: 37.693`, `measured_with_tests: true`). This is this branch's own
  note file; `_baseline.json` and the other 72 notes are untouched.
- Re-ran the required gate in the CI shape: exit 0 — `OK: 10 debt counters sit exactly
  on their ceilings and 1 progress counter sits exactly on its floor`; acceptance and
  chain mandates both OK.
- Environment sensitivity recorded for the next reader: without migrations applied (or
  without PostgreSQL), DB-backed AC tests error/skip and design coverage measures
  materially lower (33.5658 in that configuration), which fails the *floor* half rather
  than the unbanked-improvement half. The banked number is the CI-shape measurement.

## #147 acceptance re-checked at this head (executed, not inherited)

- `packages/maestro-core` delegation surfaces: `test_agent_delegate_remote_child_run.py`
  22 passed (in-process + cross-instance child Runs parented to the delegating
  Run/NodeRun; provenance names task id, mode, both agents; both escape guards fire via
  `validate_child_scope`; resolver wiring; missing-dependency loud refusals;
  `TestTheReceiptIsAttemptOwnedIdentity`), plus `test_agent_delegate_remote_review.py`,
  `test_factory.py`, `test_task_kinds.py`, `test_human_pause_reasons.py`,
  `test_answer_gated_recovery.py`, `test_container_delegation_wiring.py` — 117 passed.
- hive-conductor: `test_dag_agents.py` + `test_maistro_core_adapter.py` — 22 passed
  (ADR-082526-3ca6 AC-4/AC-5 call-time resolver wiring).
- `uv run ruff check .` / `ruff format --check .`: clean. `uv run mypy
  packages/maistro-core/src`: clean (628 files).
- `scripts/check-suite-inventory.py` for `packages/maistro-core/tests` and
  `packages/hive-conductor/backend/tests`: both match the recorded inventory.

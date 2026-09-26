---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +2
---

# auto-131 diff-coverage repair (CI run 36185294515)

Repairs the actual CI failure at `f76c0b815d` (job 108239412959, "Diff
coverage gate (per file, lines 90% / branches 80%)"): two measured files below
the 90% changed-line floor, against merge base `84402748f`:

- `packages/maistro-core/src/maistro/container.py` — 66.7% of 9 changed lines;
  uncovered 764, 767, 769 (`Container._sweep_chat_runs`: the no-admitter guard
  return, and the sweep-raises swallow that keeps retention housekeeping from
  replacing a turn's answer).
- `packages/maistro-server/src/maistro_server/api/chat_completions.py` — 80.0%
  of 15 changed lines; uncovered 238, 239, 240 (`_admit_turn`'s
  `asyncio.CancelledError` handler: the shielded
  `_cancel_incomplete_admission` compensation and the re-raise).

The publish-set floor (87%) was not the failing arm and is untouched by a
test-only change; the vulture per-identity ledger ratchet is green at this head
(1414 reviewed identities = 1414 findings, 0 unclassified, 0 never-allowlist),
so no ledger amendment was needed.

## Tests added (both arcs, meaningful behavior — not line chasing)

- `test_sweep_without_an_admitter_is_a_no_op`
  (`packages/maistro-core/tests/test_container_chat_runs.py`) — a Container
  wired without a `chat_admitter` passes through `_sweep_chat_runs` on every
  closure without reaching for a store that is not there.
- `test_a_failing_sweep_does_not_replace_the_turns_answer` (same file) — a
  sweep that raises must not fail a turn that was already answered; the Run
  still lands COMPLETED and the missed trim is logged
  ("chat Run retention sweep failed").
- `test_a_disconnect_mid_admission_compensates_and_propagates`
  (`packages/maistro-server/tests/api/test_chat_completions_gate.py`) — a
  cancellation landing between the admission hops compensates the admitted Run
  (CANCELLED + `ADMISSION_INCOMPLETE`) via the shield, and the cancellation
  still propagates.
- `test_a_disconnect_before_any_persistence_propagates_without_compensation`
  (same file) — the other arc: with no Run persisted, the cancellation
  propagates untouched and no chat Run is stranded.

## Executed at this working tree (on top of `f76c0b815d`)

- `pytest packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-core/tests/runs/test_chat_admission.py -q` — 65 passed.
- `pytest packages/maistro-server/tests/api/test_chat_completions_gate.py
  packages/maistro-server/tests/api/test_chat_completions.py -q` — 42 passed.
- Full producers under coverage, exactly as the CI coverage jobs run them:
  `coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests` (10249 passed / 684 skipped; one environmental
  failure, `test_container_postgres.py::test_an_unreachable_server_is_an_error_
  not_a_fallback`, which hangs because this workstation has live Postgres
  listeners — the service-less CI job passes it) and `coverage run --append
  --branch --source=packages/maistro-server/src/maistro_server -m pytest
  packages/maistro-server/tests` (374 passed).
- The gate itself, unchanged, at the CI merge base:
  `coverage xml` then
  `python scripts/check-diff-coverage.py /tmp/coverage-local.xml --base
  84402748f4ac3df538b0fa85beb33bc991013bb6` —
  "ok: every measured file this change touches is at or above 90% lines / 80%
  branch arcs", exit 0 (local union omits the Postgres/MinIO producers, so this
  is the stricter direction).
- `ruff check .` clean; `ruff format --check .` clean (2550 files).
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — ratchet green, exit 0.

## Issue #131 acceptance re-check (verifier duty, not inherited)

- Chat submission yields a canonical `run_id` correlated to `session_id` —
  covered by `test_a_turn_yields_a_run_id_that_resolves` (core) and
  `test_a_turn_yields_a_run_id_that_resolves` /
  `test_a_streamed_turn_yields_a_resolvable_run_too` (server); all pass here.
- Granularity/retention decisions written down —
  `docs/adr/ADR-082326-c126-chat-turn-run-granularity-and-retention.md` is in
  the tree and indexed (`check-adr-index.py` ok, recorded in the prior round's
  note; unchanged since).
- Chat-originated Runs bounded by an explicit policy, with a test proving the
  bound — `test_abandoned_stream_cleanup_enforces_the_retention_bound` (server)
  and the retention-bound tests in
  `packages/maistro-core/tests/runs/test_chat_admission.py` pass in this
  round's runs.
- Existing chat behavior parity — the full `packages/maistro-server/tests` and
  `packages/maistro-core/tests` suites pass on this tree (374 / 10249).

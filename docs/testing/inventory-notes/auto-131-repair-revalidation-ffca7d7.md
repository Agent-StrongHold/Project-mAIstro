# auto-131 repair revalidation at ffca7d7c (job 9e48f726)

Re-executed, not inherited, every deterministic check behind the prior finding
("CI at f76c0b815d: Coverage gate (publish-set floor + diff coverage) =
failure"). The failing arm at f76c0b815d was the per-file diff-coverage gate
(container.py 66.7% of 9 changed lines, uncovered 764/767/769;
chat_completions.py 80.0% of 15, uncovered 238-240); the repair commit
`ffca7d7c7` added four behavioral tests for exactly those paths. No test
inventory change this round, so no `inventory-delta:` block.

## Merge base and scope (identical to the failed CI run)

- `git merge-base origin/develop HEAD` = `84402748f4ac` — the same base the
  failing CI job diffed against.
- Three-dot changed Python files: `maistro/container.py`,
  `maistro/runs/chat_admission.py`,
  `maistro_server/api/chat_completions.py` (all measured) + four test files
  (exempt). No scripts/, canvas/, evolve/, rsi/ or bootstrap/ changes.

## Executed at this exact head (`ffca7d7c760c`)

- `ruff check .` — clean. `ruff format --check .` — 2550 files already
  formatted.
- Targeted: `pytest packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-core/tests/runs/test_chat_admission.py
  packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py -q` —
  107 passed.
- Publish-set producers exactly as CI runs them (`coverage run --branch
  --source=... -m pytest packages/<pkg>/tests --timeout=30 -q`): core 10249
  passed / 684 skipped (one environmental failure,
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`
  — killed by pytest-timeout because this workstation has live Postgres
  listeners; the service-less CI job passes it), canvas 397 passed,
  evolve 645 passed, rsi 721 passed, bootstrap 231 passed.
- **Publish-set floor, evaluated where CI evaluates it (before any
  non-publish-set data joins): `coverage report --fail-under=87` — exit 0,
  TOTAL 55,889 statements at 90%.**
- Server producer appended: `packages/maistro-server/tests` — 374 passed.
- **Diff-coverage gate, unchanged:
  `python scripts/check-diff-coverage.py coverage.xml --base 84402748f4ac` —
  exit 0, "ok: every measured file this change touches is at or above 90%
  lines / 80% branch arcs" (3 measured files, 4 exempt test files).** The
  previously-flagged hunks (container.py @761+10, chat_completions.py
  @234+7) are inside the scored set.
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0; ratchet green 1414 = 1414, 0
  unclassified. No ledger amendment needed or made.
- `python scripts/check-adr-index.py` — OK.

## Issue #131 acceptance mapping (all executed this round)

- Chat submission yields a canonical `run_id` correlated to `session_id` —
  `test_a_turn_yields_a_run_id_that_resolves` asserts
  `run.provenance[SESSION_ID_KEY] == "sess-1"`,
  `provenance["request_id"] == "req-1"`, source CHAT, and the run resolves
  from the store; server-side `test_a_streamed_turn_yields_a_resolvable_run_too`
  does the same through `/v1/chat/completions`.
- Granularity + retention decisions written down —
  `docs/adr/ADR-082326-c126-chat-turn-run-granularity-and-retention.md`
  ("One Run per turn"; retention bounded by the admitter, store bound
  source-aware), present and index-consistent.
- Bounded by an explicit policy with a proving test —
  `test_terminal_chat_runs_are_swept_behind_the_window` (10 turns,
  max_retained=3: `retained <= 3`, oldest swept, survivors are the newest),
  `test_chat_admission_does_not_evict_task_runs`,
  `test_abandoned_stream_cleanup_enforces_the_retention_bound` (server),
  `test_retention_walks_past_a_terminal_parent_with_a_child`.
- Existing chat behavior parity — `test_the_openai_shape_is_untouched`,
  `test_an_ordinary_prompt_still_runs`,
  `test_a_blocked_prompt_gets_an_openai_shaped_refusal`; full server (374)
  and core (10249) suites pass.

## Residual

- `origin/auto-131` is at `f76c0b815d` (one behind local HEAD); the repair
  commit `ffca7d7c7` is local-only. Pushing is outside this worker's
  authority, so CI-green-at-ffca7d7c is a local reproduction of both gate
  arms, not yet an observed GitHub run.
- The core-suite environmental Postgres-listener failure is pre-existing,
  unrelated to this change's surfaces, and passes in CI's service-less job.

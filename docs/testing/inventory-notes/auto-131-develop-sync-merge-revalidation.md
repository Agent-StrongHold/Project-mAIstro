---
inventory-delta:
  packages/maistro-core/tests: +0/-0 (rewritten in place: 1)
  packages/maistro-server/tests: +0/-0 (rewritten in place: 1)
---

# auto-131 develop-sync merge revalidation (job 94d95063)

The previous block left a mid-flight merge of develop into auto-131 with two
unresolved conflicts (`maistro_server/api/chat_completions.py`,
`tests/api/test_chat_completions_gate.py`). This round resolved them, merged
the two further develop commits (`394ff842`), and re-executed the evidence.

## The conflict and the resolution

The two sides had diverged on what a chat turn's admission failure means:

- auto-131 (#131): `_admit_turn` returned `Run | None`, admission best-effort,
  endpoint owned the CREATED->QUEUED->RUNNING transitions and compensation.
- develop (#1108, owner decision 2026-09-23 amending ADR-082326-c126):
  admission is mandatory; `Container._admit_chat_turn` owns the lifecycle
  transitions and compensation and raises `ChatTurnRefused` -> retryable 503.

Resolution adopts develop's #1108 contract (the ADR-recorded owner decision
supersedes the earlier best-effort rule) while keeping #131's requirements:
`_admit_turn` retains its `request_id` keyword and threads
`session_id`/`request_id` provenance into `_admit_chat_turn`, whose merged
signature carries both. The endpoint no longer duplicates the lifecycle
transitions the container owns. Two superseded best-effort endpoint tests
(`*_means_a_null_run_id_and_a_working_endpoint`) were replaced by develop's
refusal tests already present in the gate file; `test_chat_completions.py`'s
`TestAdmissionCompensation` (auto-131-only, not in develop or the merge base)
was rewritten in place from asserting 200-with-cancelled-run to asserting the
canonical 503-refusal + CANCELLED-compensation + no-dispatch contract.

## Executed at this head (7fda36aa7 = merge of 394ff842)

- `ruff check .` clean; `ruff format --check .` 2560 files already formatted.
- `pytest packages/maistro-server/tests -q` — 387 passed.
- `pytest packages/maistro-core/tests -q` — 10326 passed, 693 skipped,
  1 xfailed (0 failed this round).
- Coverage gate, both arms, producers run exactly as CI does:
  publish-set floor `coverage report --fail-under=87` exit 0 (56,134
  statements at 90%); `check-diff-coverage.py coverage.xml --base 394ff842`
  exit 0 — 3 measured files (container.py, chat_admission.py,
  chat_completions.py) at/above 90% lines / 80% branch arcs, 4 exempt tests.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 — 1412 = 1412, baseline rebased on 394ff842.
- `check-adr-index.py` — OK; ADR-082326-c126 carries both written decisions
  (One Run per turn; refusal amendment; bounded retention).

## Acceptance evidence (issue #131, at this head)

- Canonical `run_id` correlated to `session_id`:
  `test_a_turn_yields_a_run_id_that_resolves` (provenance `session_id`,
  `request_id`, source CHAT, store resolution) and
  `test_a_streamed_turn_yields_a_resolvable_run_too` — passed in the 387.
- Decisions written down: ADR-082326-c126 as above.
- Explicit bound with proving test:
  `test_terminal_chat_runs_are_swept_behind_the_window` re-run in isolation —
  passed; `test_chat_admission_does_not_evict_task_runs`,
  `test_abandoned_stream_cleanup_enforces_the_retention_bound` in the suites.
- Parity: `test_the_openai_shape_is_untouched`,
  `test_an_ordinary_prompt_still_runs`,
  `test_a_blocked_prompt_gets_an_openai_shaped_refusal` — passed in the 387.

## Residual

- One known environmental failure inside the core producer
  (`test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`)
  — this workstation has live Postgres listeners; the same test passes in
  CI's service-less job. Pre-existing, unrelated to this change's surfaces.
- Commits are local-only (push prohibited); GitHub CI green at this head is
  therefore a local reproduction, not an observed run.

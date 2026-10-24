---
# Issue #1068 Builders interactive canonical execution

Issue: #1068
Parent: #49

inventory-delta:
  packages/maistro-core/tests: +20
---

## Claim and collision boundary

The shipped `maistro builders` TUI remains the product entry point and keeps
SPEC-201's ReAct `TurnRunner` as its domain strategy. The new adapter admits
one bounded interactive turn as a canonical Graph/Run and executes the ReAct
strategy as the physical work of its NodeRun/Attempt. No Builders-private Run
store, scheduler, authorization path, or effect provider is introduced.

The CLI uses the existing `wire_execution_spine` backend selection. With no
configured deployment database it uses the CLI's private SQLite scope at
`~/.maistro/builders.db`; configured SQLite/PostgreSQL URLs use the same
canonical stores and inspection identity. Session history stores the exact
canonical `run_id` values rather than treating the local session ID as an
execution identity.

## Evidence

`test_react_turn_is_admitted_as_one_canonical_run_and_physical_attempt` proves
one interactive turn creates a scoped canonical Run, one Builders NodeRun and
one completed Attempt. The failure test proves the ReAct `max_turns` failure
settles the canonical Run and Attempt as failed rather than returning success.

`test_cli_spine_retains_run_identity_across_reopen` runs against the real
SQLite-backed spine from `wire_execution_spine` — no in-memory test shim —
and proves the persisted Run carries the local-operator actor principal
(`builders-local:<user>`, `MAISTRO_BUILDERS_ACTOR_PRINCIPAL`, or an explicit
argument, per `resolve_local_operator_principal`). Develop's #364/#1841 store
boundary rejects admission without a principal, so the shipped TUI path
admits through a real operator identity rather than a test default.
`test_local_operator_principal_resolution_precedence` pins the
explicit-argument > env > OS-user precedence and that the fallback identity is
never empty.

Cancellation remains owned by `run_durable_graph`: its cancellation handler
settles open physical work and the canonical Run before propagating the task
cancellation to Textual.

## Repair round (CI at 21d730b4c, 2026-10-19)

Four required checks failed at the synced head with one root cause: this
branch's matrix edit cited `ADR-099` in the Builders pipeline row's
*Governing ADR/spec* cell, but ADR-099 is `Proposed`, and a Proposed decision
cannot govern an active document (`scripts/check-citation-status.py`:
`matrix#Builders pipeline.governing -> maistro-engine#ADR-099`). The same
unauthorized exception red `test` (3 failures in
`tests/test_check_citation_status.py`, 5371 passed), `Coverage gate` (3
failures, 363 passed), `exact-debt-ledger`
(`check-ratchet-provenance.py`: 0 -> 1 citation exceptions), and `Validate
ADR/spec front-matter` (its `check-citation-status-provenance.py` step).

Repair: dropped `ADR-099` from the governing cell, leaving `ADR-090`
(Accepted, five-stage stage machine) and `SPEC-201` (Accepted, interactive
ReAct UX). This is also the semantics the issue requires — the shipped
interactive path must not sit under the five-stage DAG proposal, which stays
a Proposed direction, not shipped authority. No ledger amendment was used:
a new citation exception cannot be candidate-authorized (the ratchet reads
authorizations from the merge base), and the vulture ledger needed no change
(1321 reviewed identities -> 1320 findings, `unclassified: 0`).

Re-executed evidence at the repaired head: `check-citation-status.py` OK;
`RATCHET_BASE_REV=origin/develop check-citation-status-provenance.py` OK
(0 -> 0); `check-ratchet-provenance.py` all ratchets OK;
`check-shipped-surface-truth.py` OK; `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` OK;
`pytest tests/test_check_citation_status.py` 252 passed;
`check-convergence-matrix.py` OK (52 subsystems, 1414 modules);
`maistro-registry lint . --strict` OK; registry job unit battery 194 passed;
builders/cli/retention lane suites 54 passed, 9 skipped.

## Coverage repair round (CI `Coverage gate` at `1507e635`, base `origin/develop`)

The gate's failure was reproduced locally before any change, with CI's own
producer arguments (`coverage run --branch
--source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests`) and `scripts/check-diff-coverage.py
coverage.xml --base origin/develop`:

    FAIL: 3 file(s) below the diff-coverage floor
      builders/interactive.py: 86.4% of 110 changed lines (need 90%)
      cli/_builders_sessions.py: 15.4% of 13 changed lines (need 90%)
      cli/_builders_tui.py: 15.0% of 40 changed lines (need 90%)

Root cause, not a threshold: the shipped TUI's turn path, its session-run
correlation, and the adapter's own failure/teardown branches were asserted by
**source-text greps** (`test_shipped_tui_admits_turns_through_canonical_adapter`
reads the file and checks for `BuildersExecutionSpine`) and never executed.
That is the shape the diff gate exists to reject: a change whose behavior is
claimed in prose while nothing runs it.

Repair — twelve tests that drive the shipped path (delta +5 -> +17):

`packages/maistro-core/tests/builders/test_interactive_execution.py` (+6)

- `test_principal_degrades_to_bare_identity_when_the_os_user_is_unavailable`
- `test_react_dispatcher_error_settles_the_canonical_run_as_failed` — a raising
  ReAct runner produces a FAILED canonical Run carrying the real error.
- `test_cancellation_is_not_converted_into_a_turn_failure` — `CancelledError`
  propagates; `run_durable_graph` keeps ownership of cancellation.
- `test_structured_content_blocks_are_joined_into_the_turn_output`
- `test_unconfigured_spine_opens_the_private_file_backed_sqlite_scope` — proves
  the no-URL fallback is a real SQLite *file*, not `:memory:`.
- `test_configured_postgres_url_opens_the_pooled_spine_and_releases_it` —
  configured URL selects the pooled wire (asyncpg DSN normalised) and `close()`
  returns that same pool.

`packages/maistro-core/tests/cli/test_builders.py` (+6)

- `test_run_ids_accumulate_deduplicate_and_survive_a_re_record`,
  `test_an_unknown_session_is_not_created_by_a_run_notification` — session
  history keeps exact canonical `run_id`s and does not invent sessions.
- `test_a_turn_is_admitted_with_the_react_runner_as_its_physical_work` — drives
  `CodingScreen._run_agent_turn` twice through `BuildersExecutionSpine` and
  asserts the canonical admission receives the session's ReAct messages, the
  *same cached* `TurnRunner` (one execution path, one spine open, one sandbox),
  the run-id bar update and the `record_session_run` call.
- `test_a_failed_canonical_run_is_reported_with_its_run_id` — the failed-status
  branch names the canonical Run instead of reporting a successful turn.
- `test_open_coding_screen_mounts_the_session_with_its_run_ids`,
  `test_resuming_a_recorded_session_passes_its_canonical_run_ids` — resume
  carries the session's canonical Run ids into the coding screen.

Post-repair diff coverage (same command, same base): `ok: every measured file
this change touches is at or above 90% lines / 80% branch arcs`.

## Complexity repair round (CI `Quality / Radon` + `Quality / Xenon` at `5209a6524`, base `origin/develop`)

The `Coverage gate` is green at this head (publish-set floor 94% >= 87%;
diff coverage 100% changed lines on every measured file), but the quality
workflow at the same head failed `Quality / Radon`, `Quality / Xenon`, and
their aggregate `Quality gate (Pillars 1–4, 7, 8)`. Reproduced locally with
CI's own commands before any change:

    $ uv run python scripts/check-radon-baseline.py
    New complexity vs. TRUSTED baseline:
      packages/maistro-core/src/maistro/builders/interactive.py:85 run -> C (12)
    ratchet: radon ... 129 reviewed -> 130 C-or-worse blocks   (EXIT=1)

`_ReActDispatcher.run` was the one new C-ranked block the Builders change
added; it also pushed the Xenon block count 129 -> 130 (baseline 129), which
is a regression on every branch (Boy Scout Rule), not a floor raise.

Repair — no threshold change, no ledger amendment: flatten a model `content`
into the reported text with a module-level `_join_content` helper instead of
the inline `isinstance`/`and` comprehension inside `run`. The dispatcher's
result classification is unchanged: `CancelledError` still propagates,
`error`/`max_turns` stops still fail the turn, `length`/`max_tokens` stops
still settle the canonical Run `FAILED`, and text blocks still join. `run`
is now B (8) and `_join_content` A (5).

Post-repair evidence at this head: `check-radon-baseline.py` OK (129 -> 129,
0 new / 0 regressed / 0 stale); `uv run xenon --max-absolute B --max-modules B
--max-average A -i third_party ...` reports 129 block violations (baseline
129), 0 module, 0 average; `check-vulture-baseline.py` OK (1321 -> 1320,
unclassified 0); `coverage report --fail-under=87` 94%;
`check-diff-coverage.py` ok; builders/cli/retention lane suites 69 passed,
9 skipped.

Independently re-executed at the repair commit (the round above, committed):
CI's own commands — `check-radon-baseline.py` 129 -> 129, EXIT=0; xenon
129 blocks / 0 module / 0 average with no `interactive.py` row;
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` 1321 -> 1320, unclassified 0 (no ledger amendment — the
repair removed the debt instead of banking it); mypy strict clean over CI's
seven-package list (920 files); ruff check/format clean; lane suites 69
passed, 9 skipped; `check-suite-inventory.py --suite
packages/maistro-core/tests` ok (17188 collected, delta unchanged at +20).
Diff coverage for the changed file, measured from CI's own maistro-core
producer (`coverage run --branch --source=packages/maistro-core/src/maistro
-m pytest packages/maistro-core/tests --timeout=30 -q`: 16018 passed,
1163 skipped, 7 xfailed) and scored with `check-diff-coverage.py`'s own audit
math: `interactive.py` 100.0% of 115 changed executable lines (floor 90) and
100.0% of 12 changed branch arcs (floor 80); every `_join_content` line
executed. The full combine-level gate is CI-green at the parent head
(39606400250) and this delta adds eight covered statements to the publish set.

## Review-findings repair round (delta +17 -> +20)

Codex review on the shipped path flagged two P1 behaviours this adapter owned.
Both are now executed by a test rather than assumed:

- `_ReActDispatcher` treated a `finish_reason="length"` stop as a successful
  turn, so a truncated answer settled the canonical Run `COMPLETED`. Truncated
  stops (`length`/`max_tokens`) now fail the turn with
  `interactive turn truncated: <reason>`, and
  `test_a_truncated_turn_settles_the_canonical_run_as_failed` proves the stored
  Run is `FAILED` (#1068 acceptance: no failure projected as success).
- `CodingScreen` cached its `BuildersExecutionSpine` and never closed it, so the
  aiosqlite helper thread (or PostgreSQL pool user) outlived the screen.
  The spine is now opened per turn and closed in a `finally`, so no cached
  connection survives a completed or failed turn;
  `test_a_turn_releases_its_spine_even_when_the_turn_fails` covers the failure
  path, and `test_a_turn_is_admitted_with_the_react_runner_as_its_physical_work`
  asserts one open/close per turn. A lifecycle hook was deliberately not used:
  a new `on_unmount` identity cannot be banked in `quality/vulture-baseline.json`
  without a base-merged grant (two-merge rule), and the ledger must not be
  amended to authorize new debt in this round.
- `CanonicalInteractiveTurnExecutor` preserved a caller's `actor_principal_id=None`,
  which every RunStore rejects at `create_run`. The optional argument now always
  resolves the local operator principal, proven by
  `test_the_exported_executor_resolves_a_principal_when_the_caller_omits_one`.

Still open after this round (not #1068 acceptance, reported as residual): the
CLI's SQLite file/dir permissions (0644/0755 under a 022 umask) and the
`sqlite://` / `memory://` ephemeral URLs in `DATABASE_URL` are not normalised by
`BuildersExecutionSpine.open`.

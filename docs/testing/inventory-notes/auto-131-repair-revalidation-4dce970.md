# auto-131 repair revalidation at 4dce970d450ab4a3ba85145f075d78a4e6ef9f40

Verification-only round. No tests were added, so there is no
`inventory-delta:` block and no source or test-file edit.

## Snapshot

- Worktree: `/home/dev/Git/wt/auto-131`
- Branch/head: `auto-131` at
  `4dce970d450ab4a3ba85145f075d78a4e6ef9f40`
- The retention-traversal fix commit `1a9b8037d` is an ancestor of this head
  (`git merge-base --is-ancestor` returned 0).
- The worktree was clean before this note was added.

## Acceptance evidence

1. **Chat submission yields a canonical `run_id`, correlated to `session_id`.**
   `packages/maistro-core/src/maistro/runs/chat_admission.py:279-294` records
   `session_id`, `request_id`, and the retention deadline during admission.
   `packages/maistro-core/tests/test_container_chat_runs.py:51-64` resolves the
   returned Run from the Container's store and checks the chat source and
   session provenance. The server seam also returns the additive field at
   `packages/maistro-server/src/maistro_server/api/chat_completions.py:501-517`.
   The focused container and server suites passed: 102 core
   retention/execution/container/integration tests (4 expected skips) and 40
   server API tests.

2. **Granularity and retention decisions are written down.**
   `docs/adr/ADR-082326-c126-chat-turn-run-granularity-and-retention.md:52-94`
   records one Run per turn, terminalization with the turn, the 500-Run
   admitter window, source-aware store eviction, best-effort admission, and the
   bounded answer projection. `uv run maistro-registry validate` on that file
   returned one clean file with zero errors or warnings.

3. **Chat-originated Runs are bounded by an explicit policy, with a bound test.**
   `packages/maistro-core/src/maistro/runs/chat_admission.py:64-68` defines
   `MAX_RETAINED_CHAT_RUNS = 500`; `_sweep` stops at the configured window and
   catches `RunIntegrityError` at lines 337-340 so an undeletable terminal parent
   cannot strand younger Runs.
   `packages/maistro-core/tests/runs/test_chat_admission.py:407-425` is the
   regression case for a terminal parent with a terminal child: the protected
   parent remains, the younger terminal Run is removed, the new Run remains,
   and `admitter.retained == 2`. The complete
   `packages/maistro-core/tests/runs` suite passed with 862 passed and 203
   skipped. The four warnings were pre-existing aiosqlite event-loop warnings
   in `test_sqlite_store.py`; they did not fail the suite.

4. **Existing chat behavior has parity coverage.**
   `packages/maistro-core/tests/test_container_chat_runs.py:67-87` checks the
   existing OpenAI-shaped `choices` result is unchanged while `run_id` is
   additive. The server tests cover non-streaming, streaming, Gate refusal,
   failure terminalization, and admission failure behavior. The focused chat
   admission suite passed 30 tests, and the server API suite passed 40 tests.

## Commands executed

- `uv run pytest packages/maistro-core/tests/runs/test_chat_admission.py -q`
  -> 30 passed.
- `uv run pytest packages/maistro-core/tests/runs/test_chat_retention_sweep.py
  packages/maistro-core/tests/runs/test_chat_execution.py
  packages/maistro-core/tests/runs/test_chat_attempt_recovery.py
  packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-core/tests/integration/test_chat_to_graph_e2e.py -q`
  -> 102 passed, 4 skipped.
- `uv run pytest packages/maistro-core/tests/runs -q`
  -> 862 passed, 203 skipped, 4 unrelated warnings.
- `uv run pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py -q`
  -> 40 passed.
- Focused `uv run ruff check ...` and
  `uv run ruff format --check ...` -> all checks passed / 11 files already
  formatted.
- `uv run python scripts/check-adr-index.py` -> OK.
- `uv run python scripts/check-adr-status-language-provenance.py` -> 0
  contradictions and no candidate expansion.
- `uv run python scripts/check-doc-links.py` -> 1,170 Markdown files scanned,
  0 broken relative links.
- `uv run python scripts/check-suite-inventory.py` and
  `uv run python scripts/check-contract-markers.py` -> inventory and contract
  ledger checks passed.
- `uv run maistro-registry lint . --quiet` -> exit 0; 408 files checked, 0
  errors, 0 warnings, 0 extra. The command emitted the repository's existing
  citation-status diagnostics, which are not lint errors.

## Residual documentation risk

`ADR-082326-c126` is not a row in the manually maintained `ADR-INDEX.md`.
The current corpus contains 197 ADR files while the index contains 87 rows, so
this is not an issue-specific omission that can be repaired safely by adding
one row. The decision document itself is present, valid, and accepted as the
written record required by the issue; no index edit was made.

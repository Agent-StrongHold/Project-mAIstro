# auto-131 verification round at 6f6ca5e0c (job 9ceb172c)

Independent verification of the develop merge into auto-131. No test inventory
change, so no `inventory-delta:` block. Every claim below was executed at this
exact head (`6f6ca5e0cbdfb939d8799f0a56ee0e788a62914e`), not inherited.

1. Prior retention finding (chat_admission.py:317 / store.py:842,
   max_retained=2 protected-parent repro): stale at this head. Fix
   `1a9b8037d` ("fix(chat): continue retention past protected parents") is in
   ancestry. Re-executed out-of-tree: terminal chat parent holding a terminal
   child, then a 5-turn burst — `window=2 chat_in_store=2` on every pass, the
   protected parent survives, no non-terminal Run stranded, no
   `RunIntegrityError` escapes the sweep. Coverage:
   `test_retention_walks_past_a_terminal_parent_with_a_child` passes.
2. Branch-sync block from the prior round (push rejected non-fast-forward):
   resolved — `git fetch origin auto-131` then
   `git rev-list --left-right --count HEAD...origin/auto-131` = `0 0`;
   origin/auto-131 is identical to HEAD. No reconciliation or push outstanding.
3. Closure-keyword scan over `git log 84402748f..HEAD` subjects+bodies: 0
   matches for fixes/closes/resolves+`#n`; PR #1290 body says "Refs #131" only.

Executed at this head:

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py
  packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py -x -q`
  — 103 passed.
- `pytest packages/maistro-core/tests/runs -q` — 864 passed / 203 skipped
  (first broad-suite run on the merged develop head).
- `pytest .../test_chat_completions.py .../test_chat_completions_gate.py
  .../test_container_chat_runs.py -q` — 73 passed.
- `ruff check .` clean; `ruff format --check .` clean (2550 files).
- `scripts/check-adr-index.py` — OK; `scripts/check-adr-status-language.py`
  — ok, 0 contradictions.
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  and `--suite packages/maistro-server/tests` — ok (before and after this
  note).

Acceptance mapping (issue #131): run_id correlated to session_id —
`test_container_chat_runs.py:64` asserts `provenance[SESSION_ID_KEY]`;
server tests correlate the response/`X-Maistro-Run-Id` back to
`/v1/runs/{run_id}`. Granularity+retention written down —
ADR-082326-c126 (one Run per turn; admitter-bounded window, 500). Bound with
proving test — item 1 above. Parity — OpenAI response shape asserted
unchanged, `run_id` additive only. GitHub CI status for PR #1290 was not
observed this round and remains UNVERIFIED; the PR is a draft claim-stake.

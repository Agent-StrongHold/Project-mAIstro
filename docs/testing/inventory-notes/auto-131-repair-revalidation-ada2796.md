# auto-131 repair round: re-validation at ada2796a1 (job a2c4376f)

Verification-only round: no test inventory change, so no `inventory-delta:`
block. The two prior findings were re-derived and re-executed at this head,
not trusted from the earlier (provider-timeout, unfinished) job.

The fix commit `1a9b8037d` ("fix(chat): continue retention past protected
parents") is an ancestor of this head; both findings cite the tree at its
parent and are stale at it.

1. Retention past a protected parent (finding 1, chat_admission.py:317 /
   store.py:842): the exact `max_retained=2` scenario was re-executed
   out-of-tree at this head — terminal chat parent holding a terminal child,
   a second terminal turn, then a third admission. Result:
   `window=2 chat_in_store=2`, no `RunIntegrityError` escapes the sweep, the
   younger terminal chat Run is deleted, the protected parent and the
   CREATED third Run remain, and direct deletion of the parent still raises
   `RunIntegrityError` (the store's integrity rule is intact). Re-admitting
   with every turn terminal again sweeps to `window=2`; the only growth the
   sweep permits is the documented one (non-terminal Runs are never eaten —
   ADR-082326-c126), verified separately by leaving the third Run CREATED.
2. Coverage (finding 2, test_chat_admission.py:389): the gap is closed by
   `test_retention_walks_past_a_terminal_parent_with_a_child` (added by the
   fix commit, recorded in `issue-131-chat-retention-repair.md`), which
   executes that scenario directly and passes at this head.

Executed at this head:

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py` — 30 passed.
- `pytest packages/maistro-core/tests/runs -q` — 864 passed / 203 skipped.
- `pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py` — 40 passed.
- `pytest packages/maistro-core/tests/test_container_chat_runs.py
  packages/maistro-core/tests/runs/test_store.py
  packages/maistro-core/tests/runs/test_chat_retention_sweep.py
  packages/maistro-core/tests/runs/test_store_retention.py` — 53 passed.
- `ruff check .` clean; `ruff format --check .` clean (2542 files).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0, 1415/1415 reviewed identities banked,
  no unbanked identities, so no ledger amendment was required (this round
  changed no source).
- `scripts/check-execution-lifecycles.py` (19 vocabularies OK),
  `scripts/check-adr-index.py` OK, `scripts/check-adr-status-language.py` OK,
  `scripts/check-suite-inventory.py` (13 suites OK).

Branch note: the prior round's launch failure (push rejected non-fast-forward
to `auto-131`) no longer exists at this head — `origin/auto-131` is an
ancestor of `ada2796a1` (0 commits ahead), so a push from here fast-forwards.
Pushing is outside this worker's authority; the driver can push HEAD directly.

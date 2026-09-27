# auto-131 repair round: re-validation at 5dc471a6f (job 79963fb7)

Verification-only round: no test inventory change, so no `inventory-delta:`
block. The prior job (d382e1c2) died rate-limited before doing anything, and
left two findings whose fix history had to be checked against the tree rather
than trusted from either side.

1. Prior finding 1 (retention bound not enforced past a protected parent,
   `chat_admission.py:317` / `store.py:842`): re-executed the exact
   `max_retained=2` reproduction out-of-tree at this head — terminal chat
   parent holding a terminal child, then a second terminal turn, then a third
   admission. Result: `window=2 / chat_in_store=2`, the younger terminal Run
   deleted, the child-protected parent preserved, the third Run CREATED. The
   bound is enforced; the finding does not reproduce. The fix
   (`1a9b8037d fix(chat): continue retention past protected parents`) is an
   ancestor of this head.
2. Prior finding 2 (no test for retention traversal past an undeletable
   parent, `test_chat_admission.py:389`): addressed by
   `test_retention_walks_past_a_terminal_parent_with_a_child` directly below
   `test_deleting_a_run_with_a_child_is_refused`, executed and passing here.

Acceptance re-checked with executed evidence at this head (after merges
8d044dde7 and 5dc471a6f landed on the lane):

- `pytest packages/maistro-core/tests/runs/test_chat_admission.py
  packages/maistro-core/tests/test_container_chat_runs.py` — 63 passed.
- `pytest packages/maistro-server/tests/api/test_chat_completions.py
  packages/maistro-server/tests/api/test_chat_completions_gate.py` — 40
  passed (incl. `test_a_turn_yields_a_run_id_that_resolves`,
  `test_the_run_id_header_is_readable_cross_origin`,
  `test_abandoned_stream_cleanup_enforces_the_retention_bound`).
- `pytest packages/maistro-core/tests/runs -q` — 850 passed / 202 skipped.
- `ruff check .` clean; `ruff format --check .` clean (2509 files).
- `mypy` over all six packages' `src` trees — no issues in 711 files.
- `scripts/check-adr-index.py` OK; `scripts/check-suite-inventory.py` OK
  (13 suites match); `scripts/check-doc-links.py` OK.

No production or test code changed this round: the tree already satisfies
both findings, and a cosmetic change would have been the only alternative.

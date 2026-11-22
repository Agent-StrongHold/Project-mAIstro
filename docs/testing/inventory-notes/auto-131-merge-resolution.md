---
---

# auto-131 repair round: develop merge resolution (2cf218fd)

## Follow-up merge resolution (8ebbf751b, this round)

Found mid-merge again, this time with 8ebbf751b ("Expose each NodeRun's
Attempts, with the dispatched agent, on GET /v1/runs/{run_id}/node-runs
(#223) (#1548)", carrying be46a228c "Classify real content in Design trust
pre-scan (#817)"). Single conflict, resolved as union:

- `packages/maistro-server/tests/api/test_chat_completions.py`: both
  imports kept (lane's `RunStatus` for `TestAdmissionCompensation`,
  upstream's `ATTEMPT_AGENT_KEY` for the #223 attempt-exposure tests); both
  sides' test blocks already coexisted. No inventory delta — upstream's
  tests arrived with their own note
  (claude-ws-223-expose-each-noderun-s-attempts-including-c676.md) and the
  lane's tests were already inventoried.
- Everything else (trust.py, runs.py, schemas.py, test_runs_api.py,
  CHANGELOG) auto-merged; `check-suite-inventory.py` ok 13 suites after.

Evidence this round (all executed post-resolution): independent retained-bound
reproduction re-run against shipped code (max_retained=2, terminal parent with
a terminal child: window=2/chat_in_store=2, protected parent survives, younger
run forgotten, no exception escapes `admit()`), plus its negative control —
with the `_sweep` `except RunIntegrityError` neutralised, the exact prior
finding reproduces (RunIntegrityError escapes, window=3/chat_in_store=3),
proving the catch load-bearing;
`packages/maistro-core/tests/runs/` 850 passed / 202 skipped;
`packages/maistro-server/tests/api/` 356 passed; container chat batteries
83 passed / 3 skipped; ruff check/format, check-suite-inventory.py,
check-execution-lifecycles.py, check-adr-index.py,
verify-monorepo-layout.sh all OK.

No test inventory change this round, so no `inventory-delta:` block: the
develop merge unioned tests that already carried notes
(issue-131-repair.md, auto-131-0f5f.md).

The lane's worktree was found mid-merge with develop (ba2f1f07) and conflicts
in the two files this issue owns. Resolution, recorded so the reconciliation
is explicit rather than implied:

- `packages/maistro-core/src/maistro/runs/chat_admission.py` auto-merged to
  exactly the wanted union: develop's `WorkspaceRetentionScope`-scoped sweeper
  and `EXECUTION_NEVER_STARTED` compensation vocabulary, plus this lane's
  retention repair (`RunIntegrityError` caught in `_sweep` so a protected
  terminal parent cannot abort the sweep or the admission around it) and the
  public `sweep()` hook the container's post-terminalize trim calls.
- `packages/maistro-server/src/maistro_server/api/chat_completions.py`
  `_close_if_open`: took develop's canonical cancellation
  (`RunExecutionService.cancel_run`, idempotent, fenced) over this lane's raw
  `transition_run`, and kept this lane's trailing `_sweep_chat_runs()` — the
  abandoned-stream burst bound. Dropping either half reopens a defect: without
  the sweep, `test_abandoned_stream_cleanup_enforces_the_retention_bound`
  fails; without the service seam, cancellation bypasses the canonical model.
- `packages/maistro-core/tests/test_container_chat_runs.py`: union of both
  sides' imports and tests (develop's #338 stranded-admission suite plus this
  lane's `request_id` provenance assertion and
  `test_terminalized_concurrent_chat_burst_is_swept`).

Evidence this round (all executed in the worktree):

- Negative control: with the `RunIntegrityError` catch removed,
  `test_retention_walks_past_a_terminal_parent_with_a_child` fails at
  `store.py:1079 RunIntegrityError` — the prior finding's exact signature.
  Restored; 30/30 in `test_chat_admission.py` again.
- Lane battery: 101 passed across `test_chat_admission.py`,
  `test_container_chat_runs.py`, `test_chat_completions.py`,
  `test_chat_completions_gate.py`.
- Scoped suites: `packages/maistro-core/tests/runs/` 838 passed / 196
  skipped; `packages/maistro-server/tests/api/` 352 passed; container wiring
  79 passed / 10 skipped.
- Gates: `ruff check .`, `ruff format --check .`,
  `check-suite-inventory.py` (core + server) and
  `check-execution-lifecycles.py` all OK.

Environment oddity, recorded and bypassed: ad-hoc python scripts under /tmp
intermittently fail `import maestro` in this sandbox even with the src path
injected; worktree-resident pytest runs are reliable and were used for all
evidence above.

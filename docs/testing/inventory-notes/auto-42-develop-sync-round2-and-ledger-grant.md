---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 develop sync + L42 repair round 2 (heads 47d511cb5 / 0c59e3fa4)

The round began with the worktree left mid-merge by the previous worker: a
fully resolved but uncommitted merge against develop snapshot 84402748f, plus
one unstaged reconciliation edit. This note records what was concluded, what
the second (fresh) develop merge required, and the exact-debt-ledger terminal
state. No tests were added or removed; one existing test was rewritten in
place.

## Incoming salvage, concluded as-is

- The staged resolution of merge 84402748f was committed (afbc3b9d3). Its one
  unstaged piece was genuine reconciliation, not drift: develop added
  `tests/capabilities/test_pg_invocation_store.py` against the pre-branch
  `PgInvocationStore` column shape, while the branch's 607453bc0 added
  `effect_scope` to the store. The edit teaches the fake asyncpg pool the new
  `effect_scope` column; `uv run pytest
  packages/maistro-core/tests/capabilities/test_pg_invocation_store.py` = 6
  passed. Committed inside afbc3b9d3.
- 84402748f is an ancestor of the then-current origin/develop, so a second
  merge brought the remaining 20 develop commits (ca4caec7d) — chat Run-seam
  admission (#1290/#1584), session idle timeout (#1471), registration
  atomicity (#1453), synth-dag no-work failure (#1193), warden prescan
  (#1396/#1446).

## Conflict resolutions (runs store effect-claim vs occurrence-claim)

`runs/{store,pg_store,sqlite_store}.py` conflicted because both lines added a
method at the same spot: the branch's `claim_run_by_effect` /
`find_run_by_effect` (#1194 replay-effect claim) and develop's
`find_occurrence_run` (#220/#1120 occurrence claim read half). Both are
canonical and independent; each file keeps both, with `find_occurrence_run`
placed after `find_run_by_effect`. `occurrence_key`/`Mapping` imports were
already present on both sides. Evidence: `uv run pytest
packages/maistro-core/tests/runs packages/maistro-core/tests/scheduling -x -q`
= 1128 passed, 243 skipped.

## Test reconciliation forced by the merge (#1193 test vs #1194 enforcement)

develop's b632e0cd3 added
`test_a_retried_synth_dag_after_a_failed_child_starts_one_level_deeper`,
written when replay semantics were unenforced catalog metadata: it expected
`max_attempts: 2` to re-visit a failed `agent.synth_dag` in-Run (child depths
`[1, 2]`). The branch's #1194 enforcement (748e7c703) classifies
`agent.synth_dag` as `ReplaySemantics.NON_RETRYABLE` — re-running it would
re-synthesize (nondeterministic LLM call) and re-dispatch an entire sub-graph,
exactly the ambiguous external effect #1194/#42 refuse to re-execute blindly —
so `_may_revisit_after` refuses the revisit and the depths observed were `[1]`.

The test was rewritten in place as
`test_a_synth_dag_whose_child_failed_burns_depth_but_is_not_revisited_inline`,
keeping both halves of the original invariant under the enforced contract:
(a) the failed child's recursion level is still charged to the persisted
blackboard (`synth_depth == 1` read back through `mem_store.get`), and (b) the
NON_RETRYABLE contract means exactly one dispatch — `max_attempts: 2` buys no
second spawn. The depth-charging mechanics themselves are develop's, merged
cleanly in `authoritative_fold.fold_authoritative_frontier`
(`dispatched_failures` fed through `traversal._maybe_increment_synth_depth`).
Suite: `test_durable_runs.py` 23 passed; durable_runs + capabilities 197
passed, 39 skipped.

## Exact-debt-ledger terminal state (CI-repair round)

- Candidate ledger bookkeeping is clean: the merge produced develop's 1412
  banked identities + the branch's
  `...api/a2a.py::unused function 'create_a2a_task'` = 1413, matching the scan
  exactly; no stale rows, no unclassified, no never-allowlist findings.
- The sole enforcement failure is `unauthorized` for that one identity against
  trusted base ca4caec7d: `load_authorizations` reads grants from the base, so
  a candidate-side grant cannot authorize its own debt (two-merge rule,
  scripts/ratchet_provenance.py:478).
- `create_a2a_task` is not dead code: `POST /a2a/tasks/create`, mounted via
  `app.include_router(a2a.router)` (maistro_server/main.py:518), armed with
  `configure_a2a_admission` (main.py:335), replay-dedupe covered by
  `test_a2a_api.py::test_replayed_a2a_create_returns_one_canonical_run`. So
  the fix is the reviewed grant, not deletion.
- Grant landed as its own commit 0c59e3fa4 in
  `quality/ratchet-authorizations.json` (`vulture` section, owner/issue/reason
  in house style). Provenance gates accept it: check-ratchet-provenance,
  check-lifecycle-provenance, check-branch-independence, check-suite-inventory
  all exit 0.
- Measured gate states (exact brief command, min-confidence 60):
  - vs base ca4caec7d: exit 1, sole finding = the unauthorized a2a identity.
    This is the documented transitional cost; it resolves when this branch
    (grant + banked ledger + code) merges to develop, making the grant prior.
  - vs base 0c59e3fa4 (branch head, `RATCHET_BASE_REV`): exit 0, 1413 banked =
    1413 findings, zero deltas — the steady state this branch hands forward is
    self-consistent.

## Re-validation battery at 0c59e3fa4

- `uv run ruff check .` — clean; `uv run ruff format --check .` — all files
  formatted.
- pytest: runs + scheduling 1128 passed / 243 skipped; durable_runs +
  capabilities green after the test reconciliation; pg invocation store suite
  6 passed.
- Gates: check-ratchet-provenance, check-lifecycle-provenance,
  check-branch-independence, check-suite-inventory — exit 0.

## Residual

The vulture gate stays red against origin/develop until this branch merges
(two-merge rule; no GitHub mutations from this lane). Nothing else is open:
no other unbanked or unauthorized identity exists.

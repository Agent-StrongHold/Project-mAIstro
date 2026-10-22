---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-1195 verification round at d7f79d15 (independent re-derivation)

## Prior block: develop sync conflict — resolved, no action needed

The handoff reported an unresolved develop sync conflict preserved in the
worktree. At this head the resolution is already committed (`6d11ab5cd`, merge
of `origin/develop` = `20e6cd4a`, semantic resolutions documented in
`auto-1195-develop-reconciliation.md`). After `git fetch origin` the branch is
+25/-0 against `origin/develop` (0 behind), tree clean. Nothing to merge.

## Acceptance re-verification (all executed at d7f79d15)

- AC1/AC3: `jira.poll`, `jira.wait_for_subtasks`, `airtable.poll` resolve a
  capability-scoped Binding via `CapabilityEffectContext.bindings.resolve` and
  dispatch through `GovernedInvocationExecutionService.invoke` ->
  `InvocationExecutionService.invoke` (policy event + approval store +
  Invocation row carrying run/node_run/attempt/workspace/project, a
  `ResolvedBinding` provider snapshot, revision CAS and reconciliation
  history). Physical HTTP lives in
  `capabilities/providers/pm_polling.py` behind CredentialRouting — the
  canonical provider layer, not a node-local `shared_client` wrapper (stop
  condition satisfied).
- AC2: node inputs carry `binding_id` + business parameters only;
  `test_jira_poll_crosses_binding_and_invocation_without_secret_in_payload`
  asserts the credential secret appears in neither the Invocation row nor the
  event stream.
- AC4: `BindingNotFound`/`BindingDisabled`/scope-denied raise from
  `binding_store.resolve` before any HTTP; missing-binding, disabled-binding
  and missing-endpoint tests monkeypatch `httpx.AsyncClient` and assert the
  client is never entered.
- AC5: effect-history gate + atomic claim/create admission return COMPLETED
  effects without re-dispatch, block CREATED/RUNNING/UNKNOWN repeats, and only
  FAILED (`EffectNotApplied`) rows may retry; bindings are immutable and
  provider/capability-pinned. Pinned by the dedup, cross-context SQLite and
  unknown-outcome tests.
- AC6: all three nodes are retained and governed (registry
  `graph/nodes/__init__.py`, seed `daily_status.py`); no duplicate legacy
  direct-HTTP node exists in production. The remaining PM-literal sites are in
  `hive-conductor` (reference app) and carry reviewed
  `MIGRATE_TO_GOVERNED_INVOCATION` dispositions in the two-way inventory.
- AC7 (prior bypass): re-executed the runpy probe against the repaired
  `scripts/check_direct_effects.py` — graph-node `shared_client().get` with a
  fully dynamic URL, `httpx.AsyncClient` assign, `async with`, and chained
  forms all classify `DIRECT_HTTP_EFFECT:graph-node-http` (undispositioned
  sites fail the gate); non-graph control and `dict.get` stay unclassified.
  Real gate: 61 sites, all dispositioned, rc=0. Pinned by 8 unit tests in
  `tests/test_check_direct_effects.py`.

## Suites executed here

- `uv run pytest packages/maistro-core/tests/capabilities
  packages/maistro-core/tests/graph packages/maistro-core/tests/runs -q`:
  2693 passed, 306 skipped.
- Driver checks at this head: sync, ruff check, ruff format, 12-file pytest
  (169 passed, 1 skipped), suite inventory — all green (check-*.log).

## Still UNVERIFIED

- GitHub CI on PR #1321: several checks SUCCESS (Cage Guard, formal
  conformance, Gate C, exact-debt-ledger, pip-audit, DevSkim) but the main
  `CI` (test/lint/typecheck) and `quality` (pillars, coverage) workflows were
  still QUEUED/IN_PROGRESS at review time. Pending CI stays UNVERIFIED.
- Repo-wide mypy not run in-lane (not part of this lane's check manifest);
  covered by CI's lint-and-type-check when it completes.
- PR body and commit messages scanned: no premature closure keywords
  (body uses "Refs #1195" only).

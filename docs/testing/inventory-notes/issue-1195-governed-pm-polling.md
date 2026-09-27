---
inventory-delta:
  packages/maistro-core/tests: +6
---

# Issue 1195 governed PM polling

Adds four focused tests for the retained Jira and Airtable graph nodes: Binding
scope and credential routing, Invocation provenance and secret containment,
fail-closed missing Binding behavior, completed-effect deduplication, and
per-resume effect keys for Jira wait polling. The repair adds disabled-Binding
fail-closed coverage, scope provenance assertions, and SQLite-backed
cross-context retry deduplication.

## Develop reconciliation (second round, 6f460442)

The worktree arrived mid-merge of develop `8ebbf751` (four conflicted
capability/container files). Resolution notes:

- `capabilities/binding.py`: develop renamed the kill-switch field
  `enabled -> disabled` (#56). Adopted develop's field; `ResolvedBinding`
  keeps the #1195 `enabled` evidence column, now derived as
  `not binding.disabled` so a disabled Binding can never snapshot as an
  enabled-looking Invocation decision. Scope-correlation fields
  (`workspace_id`/`project_id`/`node_id`) on `ResolvedBinding` retained.
- `capabilities/binding_store.py`: develop's durable column layout
  (`payload_json` + projected scope columns, matching Alembic revision 040)
  adopted; the #1195 `PgBindingStore.ensure_schema()` retained and aligned to
  the migration's DDL so `new_postgres_effect_context` keeps working.
- `container.py`: `_wire_capability_effects` (durable Binding+Invocation
  authority plus the provisioning seam) supersedes develop's
  `_wire_capability_invocations`+`new_effect_context` pair; develop's
  `bootstrap_model_bindings(config, capability_effects)` call retained so
  operator-declared `model.chat` Bindings load into the same canonical
  authority — this is also the production `bindings.put` caller.
- `tests/graph/nodes/test_sync_kinds_branch_coverage.py`: the auto-merge
  combined our `project_id="p1"` scope with develop's credential fixture
  registered at project `"p"`, failing five llm_summarize tests with
  `CredentialScopeError`. The fixture now registers/reset the credential at
  the file's canonical `"p1"` scope.
- `tests/test_metrics.py`: unrelated pre-existing teardown StopIteration
  (the test fakes the *global* `time.monotonic`; pytest teardown timing
  consumed a third read) made deterministic-fail on this stack; the fake now
  falls back to the last scripted value. See
  `auto-1195-metrics-teardown-robustness.md`.

## Ratchet truthfulness repair (PM effect class)

A probe proved the prior "GET included in `_HTTP_EFFECT_METHODS`" fix could
not actually ratchet the PM polling class: `_HTTP_EFFECT_METHODS` is only
consulted for URLs containing model endpoints, so a new
`shared_client().get("https://acme.atlassian.net/rest/api/2/search")` in a
graph node was invisible to the gate. `scripts/check_direct_effects.py` now
also matches PM-polling URL boundaries (`airtable.com`, `atlassian.net`,
`atlassian.com`, `/rest/api/2/`, `/rest/api/3/`) as `PM_POLLING_EFFECT`;
the sanctioned provider calls in `capabilities/providers/pm_polling.py` keep
their `_PATH_CALLS` CANONICAL_INVOCATION dispositions (path rules win over
URL rules).

The strengthened boundary immediately surfaced ten real direct PM HTTP calls
in the hive-conductor Workspace backend (Jira widget poll + pagination,
Airtable cache warmers, four agent-facing Jira tools, PAT connectivity
verification) — the direct-effect escape hatch the issue warned about. Each
is now explicitly dispositioned `MIGRATE_TO_GOVERNED_INVOCATION` in
`quality/direct-effect-call-sites.json` as Workspace-cutover debt instead of
remaining invisible. Verified end to end: with a temporary rogue Jira node
the gate fails with an unclassified `PM_POLLING_EFFECT` site; on the clean
tree it passes with 61 sites, all dispositioned.

## Repair round: reachability-ledger prune for the durable effect authority

The governed effect context's PostgreSQL composition
(`new_postgres_effect_context` -> `PgEventStore`) made
`maistro.events.pg_envelope` genuinely reachable from a production entry
path (`container._wire_capability_effects`), which the reachability ratchet
correctly refused as a drift from its trusted baseline. Per the gate's own
repair instruction ("The reviewed baseline must shrink when modules become
reachable"), the module was pruned from `quality/reachability-baseline.json`
and its LIBRARY disposition entry from
`quality/reachability-dispositions.json` in lockstep. Re-probed the
direct-effects negative path (temporary rogue node, gate fails; clean tree,
gate passes) and re-ran `check-reachability`, `check-reachability-dispositions`,
`check-convergence-matrix`, and `check-ratchet-provenance` — all green.

## Independent verification round (develop-merged head, no tree changes)

After the branch merged develop `8bb344e32` (merge commit `7367bc452`), every
acceptance criterion was re-checked against reachable behavior and the prior
audit findings against the merged code — no repair was required:

- All six earlier findings are fixed in the merged tree: production
  `bindings.put` callers exist (`container._wire_capability_effects` seeds the
  provisioning seam into the durable store; `model_binding_bootstrap` loads
  operator-declared model Bindings); effect evidence is durable
  (SQLite/PostgreSQL Binding+Invocation+Event stores behind
  `new_sqlite_effect_context`/`new_postgres_effect_context`);
  `Invocation` carries and validates Workspace/Project scope correlation;
  `Binding.disabled` + `BindingDisabled` fail closed before any provider
  work; `check_direct_effects` matches GET and PM URL boundaries;
  `check-security-inventory` recomputes counted claims (exit 0).
- AC7 negative probe re-executed on the merged tree: a temporary graph node
  calling `shared_client().get("https://acme.atlassian.net/rest/api/2/search")`
  made `check_direct_effects.py` exit 1 with an unclassified
  `PM_POLLING_EFFECT` site; after removal the clean tree exits 0 (61 sites).
- Gates re-run green on the merged tree: ruff check / format (2530 files),
  mypy (714 files), capabilities 339 passed, graph 1318 passed + 79 skipped,
  runs+seeds+metrics 899 passed + 203 skipped, `tests/test_check_direct_effects.py`
  26 passed, `check-security-inventory`, `check-reachability`,
  `check-reachability-dispositions-provenance`, `check-ratchet-provenance`,
  `check-convergence-matrix`, `check-branch-independence`,
  `check-durable-table-inventory`, `check-m1-convergence-freeze` — all exit 0.

## Re-verification round after provider-timeout round (same head, no code change)

The next repair round died on a provider timeout without executing; its
"worker made no commit" result left the evidence unrecorded as executed.
This round re-executed every prior finding check and the AC7 probe from
scratch at head `a3b5e357e` (trusting nothing but the commands run here):

- Findings re-confirmed fixed: `_wire_capability_effects` seeds durable
  Binding/Invocation/Event stores (SQLite/PostgreSQL) plus the provisioning
  seam and `bootstrap_model_bindings`; `Invocation` carries and validates
  workspace/project correlation against the resolved Binding snapshot;
  `Binding.disabled` fails closed as `BindingDisabled` before any client is
  constructed; `check_direct_effects` counts GET and PM URL boundaries;
  `check-security-inventory` exits 0 (59 paths, 23 rows, 2 counted claims).
- AC7 negative probe re-executed: temporary graph node with
  `shared_client().get("https://acme.atlassian.net/rest/api/2/search")`
  made the gate exit 1 with unclassified
  `_rogue_probe.py::probe::PM_POLLING_EFFECT:pm-polling-http#1`; after
  removal the clean tree exits 0 (61 sites, all dispositioned).
- Tests re-run: `test_pm_polling_nodes.py` 8 passed; capabilities package
  339 passed; `test_sync_kinds` + branch/gap/wait suites 59 passed;
  `tests/test_check_direct_effects.py` 26 passed.
- Gates re-run: ruff check + format --check (2530 files), mypy across all six
  package src trees (714 files, success), `check-reachability`,
  `check-convergence-matrix`, `check-m1-convergence-freeze --base b906cc57`,
  and `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (unclassified: 0) — all exit 0.
- No production or test code changed in this round; evidence-only update.

## Repair-round re-execution at head 92922e050 (timeout block resolved)

The prior repair job died on its wall-clock deadline before executing anything;
this round executed every finding check and gate from scratch at head
`92922e050` and commits the evidence the missing round owed:

- All six prior audit findings re-confirmed fixed by direct code read and
  executed checks: production `bindings.put` callers
  (`container._wire_capability_effects` seeds the provisioning seam at
  container.py:1486; `bootstrap_model_bindings` at container.py:1853); durable
  Binding/Invocation/Event authorities behind
  `new_sqlite_effect_context`/`new_postgres_effect_context`; `Invocation`
  scope correlation validated against the resolved Binding (invocation.py
  184-195); `Binding.disabled` -> `BindingDisabled` fail-closed at
  binding_store.py:135 before any provider resolution or HTTP;
  `check_direct_effects` matches GET and PM URL boundaries;
  `check-security-inventory` recomputes counted claims (exit 0).
- AC7 negative probe re-executed at this head: temporary
  `graph/nodes/_rogue_probe.py` with `shared_client().get` against
  `https://acme.atlassian.net/rest/api/2/search` made the gate exit 1 with
  unclassified `...::probe::PM_POLLING_EFFECT:pm-polling-http#1`; after
  removal the clean tree exits 0 (61 sites, all dispositioned).
- Gates re-run green: ruff check + format --check (2530 files), canonical
  mypy across all six package src trees (714 files, success — this
  environment first needed `uv sync --extra bootstrap` for the
  `maistro_bootstrap` imports in `cli/_builders_tui.py`/`cli/_install.py`;
  without that extra mypy reports 5 import-not-found errors unrelated to
  this issue's surfaces), capabilities 339 passed, PM polling nodes 8
  passed, invocation-store/layer-reach + graph seeds 24 passed,
  sync_kinds/branch/gap/wait suites 59 passed, parked-run-resume + metrics
  70 passed 1 skipped, `tests/test_check_direct_effects.py` 26 passed,
  `check-direct-effects`, `check-security-inventory`, `check-reachability`,
  `check-reachability-dispositions(-provenance)`, `check-ratchet-provenance`,
  `check-convergence-matrix`, `check-m1-convergence-freeze --base b906cc57`,
  and `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (unclassified: 0 — no ledger amendment
  needed). No production or test code changed; evidence-only commit.

## Develop-sync round (origin/develop d2c74137d merged, head faf6bf522)

The branch arrived mid-merge with the develop sync conflict preserved in the
worktree (MERGE_HEAD `51058d899`, one conflicted file). Resolution:

- `container.py`: the single conflict was two unrelated functions competing
  for the same slot — our `_wire_capability_effects` (the #1195 durable
  effect-authority seam) and develop's `_identity_lifecycle_stores`
  (identity-extra tolerance). Both are called by `create_container`
  (identity stores at container.py:1943, capability effects at :1963), so
  both were kept; no behavior from either side was dropped.
- The completed merge was committed, then origin/develop (`d2c74137d`, +52
  commits) merged cleanly on top (merge commit `faf6bf522`, tree clean).

Every finding check and gate re-executed from scratch at the merged head,
trusting nothing from the pre-merge rounds:

- All six prior findings re-confirmed fixed by direct code read:
  `_wire_capability_effects` selects the durable SQLite/PostgreSQL
  Binding+Invocation+Event authorities (`new_sqlite_effect_context` /
  `new_postgres_effect_context`) and seeds the provisioning-seam bindings;
  `Invocation` carries workspace/project and `_correlate_scope` refuses a
  scope mismatch against the resolved Binding (invocation.py:171-195);
  `Binding.disabled` resolves to `BindingDisabled` in `binding_store._resolve`
  before any provider resolution or HTTP; node inputs carry `binding_id` plus
  business parameters only — secrets attach via `CredentialRouting` inside
  the provider (`providers/pm_polling.py:_provider_and_credential`);
  `check_direct_effects.py` counts `get` and matches PM URL boundaries with
  the two sanctioned provider calls dispositioned `CANONICAL_INVOCATION` and
  the ten hive-conductor PM sites dispositioned
  `MIGRATE_TO_GOVERNED_INVOCATION`.
- Duplicate-effect refusal re-confirmed in all three backends:
  `InMemoryInvocationStore.create` (invocation.py), `SqliteInvocationStore`
  (invocation_store.py:106,201) and `PgInvocationStore`
  (pg_invocation_store.py:88) all raise `UnsafeEffectRetry` on a repeat of
  an active/completed effect identity; `ResolvedBinding.from_provider`
  refuses a provider that contradicts the Binding's pinned `provider_name`.
- AC7 negative probe re-executed at the merged head: temporary
  `graph/nodes/_rogue_probe.py` with `shared_client().get` against
  `https://acme.atlassian.net/rest/api/2/search` made the gate exit 1
  ("NEW ...::probe::PM_POLLING_EFFECT:pm-polling-http#1 is an unclassified
  direct-effect call site"); after removal the clean tree exits 0 (61 sites,
  all dispositioned).
- Tests: `test_pm_polling_nodes.py` 8 passed; capabilities package 349
  passed; `tests/graph` 1467 passed + 97 skipped;
  `test_container_wiring` + `test_container_sqlite_backend` 47 passed;
  `tests/test_check_direct_effects.py` 26 passed.
- Gates: ruff check + `ruff format --check` (2587 files) clean; mypy across
  all six package src trees (724 files, success); `check-direct-effects`,
  `check-security-inventory` (exit 0), `check-credential-authority`,
  `check_enumerations`, `check-reachability`,
  `check-reachability-dispositions`, `check-convergence-matrix`,
  `check-ratchet-provenance`, and `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (1403 findings, all
  banked per-identity; unclassified 0, never_allowlist 0 — no ledger
  amendment needed) — all exit 0.
- No production or test code changed this round beyond the conflict
  resolution inside the merge commits; evidence-only commit.

## Independent verification (third round, a240cd6e)

Executed at head `a240cd6e` with develop fully merged (`HEAD..origin/develop` = 0):

- Tests: `test_pm_polling_nodes.py` 8 passed (missing/disabled-Binding cases
  assert `httpx.AsyncClient` is never constructed; repeat-poll dedup asserts
  `calls == 1` across attempts; SQLite cross-context dedup and
  unknown-outcome retry-block cases pass); capabilities + graph/nodes
  659 passed; `tests/test_check_direct_effects.py` 34 passed.
- Gates: `check_direct_effects.py` exit 0 (61 sites; PM_POLLING_EFFECT=10,
  every site dispositioned); `check-radon-baseline.py` exit 0 (65 blocks,
  0 new, 0 regressed); `check-reachability.py` and
  `check-reachability-dispositions.py` exit 0 (161 CONNECT / 24 LIBRARY /
  3 RETIRE); `ruff check .` clean; mypy across the six src trees clean
  (724 files).
- AC7 probe re-executed independently: a dynamic-URL `shared_client()`
  `async with` call and a helper-method `httpx.AsyncClient` call under a
  `/graph/nodes/` path both classify as `DIRECT_HTTP_EFFECT:graph-node-http`.
  (An initial `[]` probe result was traced to an invalid probe file —
  `ast.parse` SyntaxError, correctly ignored by design — not a bypass.)
- Closure keywords: none in commit bodies `20e6cd4a7..a240cd6e`; live PR
  #1321 body reads "Refs #1195" only (draft, head `a240cd6e`).
- Residual, recorded not resolved: 10 `hive-conductor` Workspace PM sites
  remain live direct HTTP under explicit `MIGRATE_TO_GOVERNED_INVOCATION`
  dispositions (owner #1195) in `quality/direct-effect-call-sites.json` —
  gate-enforced cutover debt per the issue's Workspace-cutover line and
  AC7's reviewed-exemption valve, not part of the migrated graph nodes.

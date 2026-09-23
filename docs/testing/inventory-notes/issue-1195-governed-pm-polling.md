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

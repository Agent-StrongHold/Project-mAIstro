---
inventory-delta:
  packages/maistro-core/tests: +43
  packages/hive-conductor/backend/tests: +21
---
# Issue #1051 — Bounded proactive discovery (M3-E5)

## What the +43 is made of (honest composition)

`packages/maistro-core/tests` **+43** = **+28 this change** plus **+15 of
pre-existing branch drift** the ledger's `--update` recording absorbed. The
change's own movement is exactly:

- `graph/nodes/test_discovery_pipeline.py` (+26): the new pipeline's
  acceptance surface — the `discovery.source` Binding allowlist refusing an
  undeclared URL before any HTTP (with a recorded transport proving zero
  connections), RSS/Atom/JSON feed parsing with per-entry source provenance,
  one governed Invocation per source fetch read back from the Invocation
  ledger, RFC 822/ISO staleness suppression generated relative to wall clock
  (a fixture with baked dates would silently rot), the budget refusal that is
  an honest output rather than a failure, context-resolved Bindings for
  scheduled fires with no HTTP caller, scout dedupe against the seen ledger
  and category down-weights from feedback, curator model strategy driven
  through the real governed model egress (fake gateway, real
  Binding/credential routing) with unparsable verdicts dropped rather than
  guessed, the lexical fallback recording its strategy, source-declared
  expiry as the only deadline evidence, surfaced-set caps from context, the
  seed validating with fail-closed defaults, and the bare context provider
  provably providing nothing.
- `test_idempotent_replay_conformance.py` (+2): conformance cases for the
  two IDEMPOTENT kinds the sweep test now demands — the fetch replay is
  GET-only against the transport and byte-stable; the scout replay is pure.

The remaining +15 predates this change: at the branch point (799b9a27, before
any #1051 test existed) the unfolded ledger already expected 15 more core
tests than the tree collected. Recording this change's delta with the ledger's
own `--update` procedure is what surfaced and absorbed that residual; the
gate balances end-to-end only with the full +43 recorded.

`packages/hive-conductor/backend/tests` **+21** (exactly this change's
movement; the branch point was drift-free there):

- `test_discovery_service.py` (+21): the Workspace product half against the
  real Workspace authority — the off switch, config bounds, durable day-keyed
  budgets charged once per Run id (and reset by the day key), refusal before
  admission, fire-time context notes assembled from persona/user-model/goal
  seams, feedback down-weights, lift idempotency per Run, cross-cycle
  duplicate suppression, surfaced-set caps, dismissed/stale filtering with
  source expiry keeping an item alive past the default window, non-members
  and missing Workspaces looking identical, Attention projecting discoveries
  as proactive Waiting with only source-declared expiry escalating
  (never to blocking), Home adaptive candidates carrying the explain
  evidence, keep/dismiss recording Attention dismissal plus category
  preference state, and a full trigger→lift→feedback cycle leaving the
  durable user model byte-identical (external content stays sourced
  evidence; promotion stays behind the canonical consolidation door).

## Why the counts differ in kind

The core suite proves the canonical execution seams (Binding/Invocation,
effect keys, replay semantics, fail-closed refusals); the conductor suite
proves the product behavior around them (budgets, preferences, projections).
Neither mocks the other's authority: core tests run the governed egress with
real Binding/credential routing, conductor tests run the real Workspace
authority with only the Run trigger faked at its single seam
(`services.dag_agents.run_registered_dag`), because the canonical spine that
seam drives is exactly what the core suite already proves.

## Repair round (same change, before landing)

The first cut of the discovery code tripped all three quality ratchets. The
repair is behavior-preserving — the 26/2/21 tests above pass unchanged in
assertion content (one dead helper's two assertions re-target the context
fields directly):

- **radon/xenon**: the three node `_execute` bodies, `_parse_json_feed` and
  `create_container` were split so every new block grades B or better
  (`_cycle_floor`/`_scored`/`_candidate`/`_capped`, `_declared_sources`/
  `_binding_for`/`_invoke_source`/`_accept_entries`, `_refusal_out`/
  `_empty_out`/`_merged_notes`/`_validated_strategy`/`_apply_cap`,
  `_json_items`/`_json_field`/`_json_entry`, and the backend selection
  extracted into `_wire_backend_stores` over `_BackendStores` — the same
  move #122 made for `_wire_prompt_manager`). The xenon block count returns
  to the pinned 124, one-for-one with the radon ledger.
- **vulture**: the eight telemetry/payload fields (`seen_suppressed`,
  `below_floor`, `sources_queried`, `skipped_stale`, `dropped_unparsable`,
  `dropped_low_confidence`, `matched_context`, `curated_at`) are
  serialization-only inside `packages/*/src` — their consumers are the
  pipeline tests and the host's lift path, which sits outside the scan root.
  They are acknowledged inline (`# noqa: vulture` with that rationale), the
  analyzer's documented mechanism and the repo's in-src precedent, because
  this lane cannot land the `pydantic-declarative-field` ledger rows a floor
  raise would need (two-merge ratchet: grants authorize from the merge base).
  Counters are now accumulated locally and set through constructors, so no
  attribute-write sites remain. The genuinely dead
  `DiscoveryCycleContext.binding_id_for` was removed rather than banked.

## Post-verification repair (reachable path)

Post-merge verification found the per-Run charging above was not reachable:
the Protocol carried no cycle key, so no production caller could name its
Run and the ledger billed per context read. The repair — nodes pass
`ctx.run_id`, the host charges keyed reads idempotently, tests exercise the
wired provider shape, and the discovery provider's guarded-redirect refusal
is pinned — is recorded with its own deltas in
[`1051-reachable-path-charging-repair.md`](1051-reachable-path-charging-repair.md).

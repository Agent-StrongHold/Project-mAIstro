---
inventory-delta:
  packages/maistro-core/tests: +50
  tests/: +4
---
# 301 per-Workspace working-memory projection (Ladybug-shaped hot layer)

Implements #301 / ADR-082226-5104 §5–8: a MAIstro-owned `WorkingMemory`
protocol, a per-Workspace indexed projection behind it (BM25 inverted index,
write-time stored embeddings, entity/mention/co-occurrence graph), a manager
with lazy idempotent hydration from the authoritative episodic store, idle-TTL
eviction and discard-and-rebuild, and the Layer 1 / Layer 4 wiring in
`DefaultContextAssemblyPolicy` — Layer 4 stops returning the placeholder `""`
for a populated Workspace. Design and the ADR-039 dependency review (no
`ladybugdb` dependency; it does not resolve from the registry) are in
`docs/architecture/working-memory.md`.

All additions, no removals:

- `packages/maistro-core/tests/memory/working/test_working_memory.py` —
  protocol conformance, idempotent hydration, BM25-vs-overlap ranking, the
  one-embed-per-read proof, scope preservation (agent/org/project/weight),
  update re-index + re-embed consistency, failed-embed degradation (lexical
  only, never stale vector), model-identity drift dropping stale vectors,
  entity MentionedIn/co-occurrence/traversal, delete pruning, cross-Workspace
  isolation with identical ids and entity names, evict/rehydrate, reset,
  TTL sweep, hydration-read failure recorded, backend init failure raising
  `WorkingMemoryError`, rebuild recovery, and the read-only Dreaming
  candidate set.
- `packages/maistro-core/tests/memory/working/test_working_context_layers.py` —
  Layer 1 hot path (with the empty-query and degradation fallbacks), scope
  narrowing through the policy, real Layer 4 graph context for a populated
  Workspace with provenance rendered, project narrowing, empty/degraded
  honesty (returns `""`, never fabricates), `assemble` integration, and the
  no-manager compatibility path.

## Repair round (exact-debt-ledger + suite inventory, this branch)

Three follow-ups landed with the merge-queue repair, +4 tests net over the
+46 recorded above (one `6483436e9` regression test post-dated that note;
three are new below). The `tests/: +4` line records
`tests/memory/test_working_projection_fingerprint.py` from `38bd63dc9`,
which landed on this branch without its own delta note.

- `test_candidate_set_groups_disjoint_entity_neighbourhoods` (+1) and a
  cluster assertion on the existing candidate-set test: `collect_candidates`
  now derives connected co-occurrence clusters via bounded
  `projection.traverse` walks — the "clustering" half of ADR-082226-5104 §7
  that the candidate set claimed but did not expose.
- `test_access_sweeps_idle_projections_and_counts_them` (+1): the idle-TTL
  sweep runs amortized at `WorkingMemoryManager.projection()` access (the
  graph being served is touched first and can never evict itself), with the
  lifetime `evictions` / `active_workspace_ids` telemetry in the sweep log.
- `test_mid_read_failure_heals_by_rebuild_for_the_next_call` (+1): a
  projection that constructs but fails mid-read (the observable corruption
  signal) triggers one throttled `manager.rebuild()` — discard + rehydrate
  from authoritative truth, no durable write — so the next call is hot
  again instead of degraded until restart.

### exact-debt-ledger disposition (vulture per-identity ledger)

The trusted base (`430139cb`, this branch's merge-base) landed with a stale
ledger: its identity module already lived in `_crypto.py`/`principal.py`
while the ledger still recorded the methods at `identity/__init__.py::`, and
its 29 new identities carried no grants. Because ratchet authorizations are
read from the base revision (two-merge rule, per `scripts/ratchet_provenance.py`),
the identities had to be eliminated in code, following the #768/#817 repair
playbook:

- **Wired to real consumers** (15): `recall_lexical`/`recall_vector` are now
  what `recall()` is composed from (one query embed preserved);
  `entity_context` reads relations through the public `relations_for` (the
  private twin is gone); Dreaming candidate sets use `traverse` for cluster
  derivation; `degraded_reason` is surfaced in the policy's fallback logs;
  `evict_idle` is the manager's amortized sweep (logging
  `evictions`/`active_workspace_ids`); `rebuild` is the policy's throttled
  corruption-heal path.
- **Removed as genuinely unreferenced** (1): `WorkingMemoryManager.hydrate_workspace`
  had no caller in src or tests; `projection(wid).hydrate(records)` is the
  same raising, report-returning operation one call away.
- **Removed as genuinely dead** (1 finding): the write-never, read-never
  `_WorkspaceCounters.degraded_reason` field.
- **Whitelist-referenced** (12): the identity extra's tested public seed API
  (`ConductorSeed.from_mnemonic/derive_named/did_key/mnemonic_words/zero`,
  `DerivedKey.curve`, the module `__getattr__` lazy loader) and Principal's
  ADR-068 legacy-dict bridge, plus the `WorkingMemoryStats` observability
  fields — consumers are downstream products and the identity/stats test
  suites, the exact category `_vulture_whitelist.py` documents.
- One side effect, recorded here on purpose: referencing `__getattr__` makes
  the name used scan-wide (vulture is name-global), which also cleared the
  banked `archive`/`auth`/`maistro_design`/`maistro_rsi` `__getattr__`
  findings; those ledger rows are pruned with this change.
- The candidate ledger prunes the 6 stale `identity/__init__.py::` rows and
  the 4 cleared `__getattr__` rows (1374 → 1364 findings, all classified,
  none unbanked).

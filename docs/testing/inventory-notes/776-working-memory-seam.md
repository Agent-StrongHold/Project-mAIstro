---
inventory-delta:
  packages/maistro-core/tests: +26
---

# 776 — per-Workspace working-memory seam (M3 product floor)

Issue #776 adds the minimum per-Workspace Ladybug working graph
(ADR-082226-5104): a disposable, non-authoritative projection of durable
memory that the persistent Workspace Agent can hydrate lazily, query, discard
and rebuild, under `maistro.memory.working_graph`.

The 26 new `packages/maistro-core/tests/memory/working_graph` node IDs cover
the acceptance properties that make the seam real rather than a claimed
abstraction:

- hydration happens lazily on first use, from the engine's **real** in-process
  episodic and learning stores, and is bounded;
- retrieved context retains canonical references (memory/learning/artifact/
  run/node_run/attempt/project/goal/workspace ids); a consumer rendering or
  quoting the context quotes the node's canonical ref data (its `to_dict()`
  carries the durable identities plus the org/team/user scope ids);
- a durably recorded user correction becomes visible only through
  hydration/re-read — the projection never invents it early and never invents
  facts on an empty graph;
- accepted and rejected artifact versions hydrate with lineage and
  produced-during linkage;
- Run provenance keeps Goal and parent-Run linkage, and one traversal hop
  reaches a memory's producer Run and its parent (the transcript linkage
  Dreaming will consume under #301/#1047);
- two Workspaces with colliding identifiers — even served by one manager and
  one source — never observe or traverse each other's graph; a backend refuses
  a foreign Workspace's records, and a mis-scoped hydration source is refused
  loudly instead of poisoning a graph;
- discard/rebuild loses nothing durable (durable reads re-verified unchanged);
- a broken backend reports UNAVAILABLE and a partially failing source reports
  DEGRADED, with the reason surfaced in `GraphContext`/`WorkingMemoryStatus`
  and logged at the manager seam boundary, while durable reads still succeed;
- manager lifecycle: one graph per Workspace identity, LRU eviction disposes
  (closes) the least recently used graph, per-Workspace `discard` removes the
  projection from the manager's map, and blank Workspace ids are refused
  explicitly.

## CI-repair round (exact-debt-ledger + formal-conformance, this branch)

No node IDs were added or removed in the repair round; the suite is still the
same 26 tests (438 collected in `tests/memory`), so the recorded inventory is
unchanged. Assertion-shape edits only:

- `test_retrieved_context_retains_canonical_references` now asserts the
  canonical references on `node.ref.to_dict()` data instead of the removed
  `GraphContext.to_text()` rendering;
- `test_correction_recorded_durably_becomes_available_after_refresh` re-reads
  via `graph.hydrate()` (the incremental, idempotent path) after
  `WorkspaceWorkingMemory.refresh()` — a pure alias — was removed as dead
  code for the vulture per-identity ledger;
- `test_lazy_hydration_happens_on_first_use` asserts hydration via
  `status.health is HEALTHY` (+ `node_count`) after the write-only
  `WorkingMemoryStatus.hydrated`/`last_hydrated_at` fields were removed
  (`health` already encodes hydration: COLD = not hydrated);
- `test_lru_eviction_discards_oldest_graph` and
  `test_discard_clears_each_projection` (renamed from
  `test_discard_all_clears_every_projection`) assert manager map state through
  `status()`/`discard()` behaviour after the uncalled introspection helpers
  `active_workspaces()`/`discard_all()` were removed as dead code;
- `test_unavailable_backend_reports_degraded_state_and_durable_intact` gained
  a caplog assertion pinning the manager's new seam-boundary degradation log
  (the genuine production read of `GraphContext.degraded_reason`).

## Independent verification round (head 3c4eabd6cd49, base b268f05359e7)

Executed locally, all observed directly:

- `pytest packages/maistro-core/tests/memory/working_graph -q` → 26 passed;
  `pytest packages/maistro-core/tests/memory -q` → 438 passed; `ruff check` /
  `ruff format --check` clean; `check-suite-inventory.py` ok.
- formal-conformance steps, against a real pgvector/pg18 Postgres (fresh
  container, `alembic upgrade head` applied): `check-m1-convergence-freeze.py
  --base b268f05359e7` pass; `check-formal-oracle-independence.py --base
  b268f05359e7` pass; `pytest formal/models/ --timeout=300
  --hypothesis-seed=0` → 664 passed.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → 1402 reviewed → 1401 findings, exit 0.

**Still red — exact-debt-ledger is NOT fixed at this head:**
`scripts/check-ratchet-provenance.py` exits 1 (step "Require enforced ratchet
provenance policy", `.github/workflows/vulture-ratchet.yml`, which runs before
the vulture step the previous repair fixed). Root cause: the reachability
ratchet reports the six new `maistro.memory.working_graph*` modules as NEW
unreachable (unrooted — no production/CI entry point imports them) modules,
absent from `quality/reachability-baseline.json` (189 entries, none
working_graph), with no group in `quality/reachability-dispositions.json` and
no `reachability` authorization in `quality/ratchet-authorizations.json`.
`scripts/check-reachability.py` exits 1 for the same reason. Repo convention
for an intentional published seam (see the `wiring-reads` precedent) is:
baseline the modules, add a disposition group naming the root that will reach
it (plus the matching CONVERGENCE-MATRIX row), and record the ratchet
authorization with owner/issue/reason. The earlier repair note's "exact CI argv
now exits 0" claim held only for the vulture sub-step, not the job.

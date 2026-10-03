---
inventory-delta:
  packages/maistro-core/tests: +35
---

# 776 — per-Workspace working-memory seam (M3 product floor)

> Round note (CI-repair verification, head 82a80eacf): every gate the last
> merge-queue evaluation reded was re-run locally against the merged head —
> no code change was needed this round; the failures at b8a897882 predate the
> develop-merge defect fix (ed11b3d4f) and the merge itself. Evidence:
> `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
> '*/third_party/*'` exit 0 (1359 reviewed → 1359 findings); `pytest
> formal/models/ --timeout=300 --hypothesis-seed=0` → 663 passed, 1 skipped
> (CI-style editable installs of formal/, maistro-core, maistro-evolve plus
> alembic upgrade head against a real server); `check-diff-coverage.py
> coverage-core.xml --base 053f93969` → ok at 90% lines / 80% branch per
> measured file; full `packages/maistro-core/tests` → 11381 passed, 782
> skipped, 1 xfailed (REQUIRE_AUTH=false, MAISTRO_DRY_RUN=1); PG-backed
> `test_container_postgres.py` + `persistence` + `workspaces` → 968 passed
> (MAISTRO_TEST_PG_DSN against the migrated server);
> `tests/migrations/test_migration_chain.py` → 13 passed; radon 145 → 145,
> reachability, wiring-reads, contract-markers, convergence-matrix,
> promotion-surface, owned-store-access, agent-store-writes,
> credential-authority, security-inventory, ratchet-provenance, M1 freeze and
> formal-oracle-independence (base 053f93969) all exit 0; ruff check/format
> clean; `check-suite-inventory.py` ok (no node IDs changed). One local-only
> artifact worth recording for the next verifier: under `coverage run`,
> `test_an_unreachable_server_is_an_error_not_a_fallback` can hit the
> coverage producer's `--timeout=30` because this WSL environment stalls the
> port-1 connect ~60s instead of refusing instantly as CI runners do; the
> same test passes under coverage with `--timeout=120` and standalone, and
> the branch touches no connection code — environment timing, not a
> regression.

> Round note (develop-sync repair, this branch): the branch merged
> `origin/develop` (fa2deb0a4, 28 commits) — no textual conflicts, but one
> semantic merge defect had to be resolved: develop's `create_container`
> passes `project_store=` / `project_scope_store=` into the `Container`
> constructor, and this branch's earlier removal of the (then-dead)
> compat field won the silent merge, leaving `project_scope_store=None` in
> every in-memory container — 77 test failures across the runs
> consumption/parked-run/claim-recovery/lease and container wiring/chat
> suites. Resolution: took develop's side (compat field and both kwargs
> restored). Evidence at the fixed head: full `packages/maistro-core/tests`
> → 11599 passed, 117 skipped, 1 xfailed (PG DSN set; previously 77 failed);
> `pytest formal/models/ --timeout=300 --hypothesis-seed=0` → 664 passed
> (pgvector/pg18, fresh `alembic upgrade head`); `ruff check` /
> `ruff format --check` clean; `check-suite-inventory.py` ok (suite grew to
> 11717 recorded node IDs via develop, +0 from this round — no node IDs
> added or removed); `check-vulture-baseline.py` exit 0 (1390 reviewed →
> 1389 findings; the seam's LRU eviction legitimately calls
> `OrderedDict.popitem`, so `runs/model.py::popitem` is no longer a finding
> and its pruned bank entry stays pruned); `check-reachability.py` exit 0
> (188 unreachable = baseline); `check-ratchet-provenance.py` exit 0.

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

## Merge-queue repair round: production wiring for the seam (this branch)

The merge-queue evaluation failed `formal-conformance` against develop base
`0fb3dc69e`, and re-running the named gate faithfully (CI's pip-install steps
mirrored, fresh pgvector/pg18, `alembic upgrade head`, `pytest formal/models/
--timeout=300 --hypothesis-seed=0`) passes with 664 tests at the develop merge
— but the exact-debt-ledger gates were still red for the reason the previous
round recorded: the six `maistro.memory.working_graph*` modules had **zero
production importers**, so `check-reachability.py` (and the trusted-base gate
`check-reachability-provenance.py` behind `check-ratchet-provenance.py`)
reported them as NEWLY UNREACHABLE. A published seam nothing can reach also
left acceptance criterion 4 ("the persistent Workspace Agent can retrieve
graph-backed context") true only at the seam level.

This round wires the seam instead of baselining it away:

- `maistro/memory/working_graph/wiring.py` (new): the deployment half of the
  seam — `WorkspaceProjectMemorySource` (episodic memories scoped to the
  Workspace's own Project tree, the one workspace-honest durable scope that
  exists today), `WorkspaceRunStoreProvenanceSource` (Run provenance via the
  Run store's `workspace_id` axis), `build_workspace_working_memory` (the
  Container's manager factory), and `working_memory_context_message` /
  `render_working_memory_block` (the chat-turn consumer glue). Learnings,
  artifact versions and terminology are deliberately not wired yet — the
  module docstring records why (no workspace-honest durable axis / no durable
  store exists; the ports are ready for #773/#777).
- `maistro/container.py`: `working_memory` field wired in `create_container`
  from the same episodic/project/run stores everything else reads, and the
  chat turn dispatches with the graph-backed context block rendered from the
  turn's Run's own Workspace. The block rides as a system message (never a
  user turn: not Warden-scanned as input, not session-transcribed, message
  shape unchanged), carries canonical durable references, and renders an
  explicit degraded/unavailable state instead of a confident blank.
- 9 new tests in `packages/maistro-core/tests/memory/working_graph/
test_wiring.py` (+9 node IDs, delta above updated 26 -> 35): workspace-
  scoped context with canonical refs, cross-Workspace absence (colliding
  query, records simply not there), honest-empty unknown Workspace,
  Goal/parent-Run provenance linkage, degradation named in the block with
  durable truth intact, durably recorded correction visible on the next
  turn, discard/rebuild leaving durable reads unchanged, no-manager/blank-
  workspace/no-user-text refusals, and the renderer's health/cap contract.

Gate evidence at this head (all executed locally, pgvector/pg18 via
`DOCKER_HOST=unix:///var/run/docker.sock`): `check-reachability.py` exit 0
(1149 modules, 189 unreachable = baseline, no NEW unreachable);
`check-ratchet-provenance.py` exit 0 with `RATCHET_BASE_REV=0fb3dc69e`
(including the `reachability` and `reachability-dispositions` ratchets);
`check-formal-oracle-independence.py --base 0fb3dc69e` exit 0;
`pytest formal/models/ --timeout=300 --hypothesis-seed=0` 664 passed;
`pytest packages/maistro-core/tests/memory -q` 447 passed.

### Repair-round validation on the salvaged wiring (final head of this branch)

The wiring round above timed out uncommitted before its own full validation;
this round finished it and ran the whole battery at the final tree. One real
regression surfaced and was fixed:

- `runs/test_chat_execution.py::TestInAgentDelegationCreatesNoNodeRun` (2
  tests) failed with the seam wired: the delegation turn's messages now always
  carry a prior trusted system message (the working-memory block), so
  `Agent._prepare_user_input` passes Warden's real keyword-only `context=`
  parameter (`security/warden/detector.py:435`, the documented optional
  analysis-context contract) — and the test's `_Warden` stand-in predated
  that contract (`scan(self, _text, _surface)`), crashing the coordinator
  with `TypeError` before it could delegate. Assertion-shape edit only: the
  stub now takes `**_kw` like the real contract; the tests' delegation-spine
  claims (exactly one NodeRun; Attempt names the delegate) are unchanged and
  pass again.
- Full-suite evidence with the seam wired: `pytest packages/maistro-core/tests
-q --timeout=300` → 10824 passed, 735 skipped, 1 xfailed, plus
  `tests/integration` → 5 passed with `MAISTRO_TEST_PG_DSN` set — the
  recorded 11565 node IDs all green; `ruff check` / `ruff format --check`
  clean; `check-suite-inventory.py` ok at +35; mypy over
  `packages/maistro-core/src` reports only the pre-existing environmental
  `maistro_bootstrap` import-not-found notes in `cli/_install.py` /
  `cli/_builders_tui.py` (bootstrap not installed in this env; files untouched
  by this branch).
- The named failing merge-queue gate, `formal-conformance`, re-proven end to
  end at this exact tree: fresh `maistro_test` database in a pgvector/pg18
  container, `alembic upgrade head` exit 0, `pytest formal/models/ -q
--timeout=300 --hypothesis-seed=0` → 664 passed, plus
  `check-m1-convergence-freeze.py --base 0fb3dc69e` and
  `check-formal-oracle-independence.py --base 0fb3dc69e` both exit 0.
  (`formal/` needs `maistro-evolve` importable; mirrored CI's explicit
  `pip install -e packages/maistro-evolve` with `uv pip install -e`.)
- Exact-debt-ledger gates re-run at this tree: `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0
  (1402 reviewed → 1401 findings), `check-ratchet-provenance.py` exit 0 with
  `RATCHET_BASE_REV=0fb3dc69e`, `check-reachability.py` exit 0.

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

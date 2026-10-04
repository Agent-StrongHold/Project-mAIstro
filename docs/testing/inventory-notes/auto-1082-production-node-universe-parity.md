---
inventory-delta:
  packages/maistro-core/tests: +78
---

# Production node-universe parity for the composition guards (#1082)

Closes the 2026-10-03 residual audit's evidenced gap: both composition sweeps
(`test_node_composition`, `test_container_node_composition`) derived their
universe from process-local `list_kinds()` at collection time, which proves
only whatever registration modules the current pytest process happened to
import. The CI core job never imported `maistro_design.creative_graph`, so the
eleven `creative.*` kinds that `scripts/check-reachability.py` counts as
reachable production source were invisible to both sweeps — a future authority
declaration in that production module would have escaped the generic guard
through import/collection order alone. The existing checks were *not* wrong
about the kinds they covered; the hole was that nothing tied their universe to
production source identities.

## What moved (+78 node IDs in `packages/maistro-core/tests`)

**+42** in `test_production_registration_universe.py` (new, 13 test
functions; one parametrized over the 30-kind universe). It pins the
reconciliation the guards now run, from
`packages/maistro-core/tests/graph/nodes/_production_registration.py`:

- **Source identities**: an AST scan (so the many prose mentions of
  `register_node` in docstrings never fabricate a module) over
  `check-reachability`'s own `_all_package_python_files` production universe —
  the reviewed classification, reused rather than re-derived, with its
  test-shaped-file exclusions keeping fixture registrations out of the proof.
- **The reachability ledger**: `quality/reachability-baseline.json` decides
  reachable vs unreachable (kept accurate by the existing reachability gate,
  which fails a newly unreachable module until baselined and a baselined
  module that becomes reachable until pruned). Every reachable registration
  module is imported by the helper at import time — `maistro_design.creative_nodes`
  included, the same module production executes when the Conductor imports
  `creative_graph`. Every unreachable one must carry a reviewed disposition in
  `quality/reachability-dispositions.json`, and its kinds stay out of the
  proof.
- **The registry**: after loading, every non-`test.*` registered kind must be
  defined in a loaded, reachable registration module.

The negative cases run that exact reconciliation against synthetic trees: a
reachable registration omitted from loading is detected
(`reachable_omitted`), an unreachable one without a reviewed disposition is
detected, test-shaped registrations never enter the universe, and a
registration outside a packaged `src` root fails closed. A subprocess probe
executes the audited selection difference itself: a bare core import
registers 19 kinds and no `creative.*`; importing the real design registration
module adds exactly the eleven the reconciled universe attributes to it.

**+33** in `test_node_composition.py` — no new assertions, the existing
generic parametrizations (declaration validity, exact-identity composition,
bare-resolver refusal) now run over the reconciled 30-kind universe instead of
the 19 the core process used to see.

**+3** in `test_container_node_composition.py`: a parity test pinning the
declaring sweep inside the reconciled universe, a whole-universe
Container-composition test (every production kind resolves through
`Container.node_resolver()` to the registered class — the creative kinds
participate without hand-written per-kind assertions), and the Warden seam pin
described below.

## Justified differences from the reachability universe

`maistro_design.nodes` registers `design.orchestrate` and
`design.consistency_eval` but is classified unreachable, with the reviewed
`design-node` disposition (CONNECT): it sits outside the `maistro.graph.nodes`
catalog sweep, no production entry point imports it, and the kinds are never
registered in a production process. The guard therefore neither loads it nor
sweeps its kinds as production proof — and a test asserts the exclusion is the
*reviewed* one: if the module becomes reachable, the reachability gate forces
the ledger to change, and the guard then requires loading it. Today's totals:
19 core kinds through the catalog sweep, 11 creative kinds through
`creative_nodes`, 30 proved; 2 design kinds consciously outside the proof.

## Warden resolution (issue #1082, step 3)

Recorded exclusion, not an omission: no node-level Warden or Sentinel
authority exists in `AUTHORITY_NAMES`. The Container owns a Warden for its own
gate wiring (`Container.warden`, `warden_scan`); a node's `warden`/`sentinel`
constructor parameters are intentional local strategy seams whose defaults are
the #1165 fail-closed pair — a fresh `Warden()` and a `Sentinel` with an empty
permission table, deny-on-miss, no governed permission source
(ADR-072726-0d6b, owner @BlakeMatthews-dev; default-deny invariant preserved
by #1165's pins in `test_container_security_wiring.py` and
`test_agent_synth_dag.py`). Canonicalizing any surviving node/component Warden
dependency into a Container authority is the Security-on-Agent workstream
(`docs/architecture/WORKSPACE-CUTOVER-PLAN.md`, "Security on Agent" row: #66,
#1171, #1202), not this composition closeout; no permission source was
invented, synth execution stays disabled without a governed grant, and no
security policy changed. `test_the_production_resolved_synth_dag_keeps_its_default_deny_seam`
pins the seam on the production-resolved node (its Warden is not the
Container's; empty table, compatibility mode unarmed, no permission source) so
the decision cannot drift silently in either direction.

## Where this executes in CI

The exact guard runs in the `test` job of `.github/workflows/ci.yml` —
`uv run pytest packages/maistro-core/tests -v --tb=short` (with
`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`), which fires on pushes to
main/integration/develop, pull requests and merge groups. The core and design
suites run in separate pytest processes; loading the design registration path
inside the core suite is what removes the process boundary from the proof.
The source-universe side reuses `check-reachability.py`'s reviewed
classification rather than re-deriving it; the reachability job remains the
authority on reachable/unreachable classifications.

Local evidence at this head: the two sweeps plus the new guard run together
for 150 passed (the audited baseline was 72 core-only, 105 with the design
import forced); `test_model_egress_container_composition.py` +
`test_agent_delegate_remote.py` still pass 19; the full CI core command
passes 12041 (+78 vs its recorded inventory).

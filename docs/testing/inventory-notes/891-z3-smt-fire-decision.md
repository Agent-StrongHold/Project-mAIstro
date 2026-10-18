---
inventory-delta:
  packages/maistro-core/tests: +12
---

# #891 Z3/SMT fire-decision experiment (M8-A11 prototype)

Bounded research prototype: the schedule fire/skip decision core
(`packages/maistro-core/src/maistro/scheduling/engine.py`) encoded as an SMT
contract in Z3 and differentially certified against the production function
over the whole bounded cell grid (336 cells), plus a bounded closed-loop
BUFFER_ONE starvation model, unsat-core explainability queries, measured
teeth guards, and a source-scan guard keeping the solver out of
`packages/*/src`.

New files, all under `packages/maistro-core/tests/scheduling/`:

- `_z3_fire_contract.py` — the machinery: `FireContractModel` (the
  documented contract as SMT constraints; conformance, uniqueness,
  divergence-witness and unsat-core queries; deliberate-mutation flags),
  `BufferedStarvationModel` (four-tick closed loop over arrivals, the held
  occurrence, symbolic run lengths, and the fire budget), and the grid
  driver producing real `Schedule` cells.
- `test_engine_z3_conformance.py` — 12 node IDs: whole-grid conformance and
  uniqueness walks, the teeth guards, the explainability cores, the
  starvation questions (parametrized over three budgets), the never-ending
  run witness, the exhausted/disabled short-circuits, the horizon
  out-of-scope pin, and the z3-absent-from-production-sources scan.

`z3-solver` is a dev-only dependency (both dev lists in `pyproject.toml`);
the source-scan test enforces the issue's non-goal that no solver runtime
dependency reaches production. Net: +12 collected node IDs on
`packages/maistro-core/tests`. Experiment record and WATCH disposition:
`docs/testing/z3-smt-decisions-evidence.md`.

# Round-2 repair notes for issue #881 (`auto-881`, head `7de64585c1f5`)

## What actually failed at the last evaluation

The named CI gate was `exact-debt-ledger`. Running its steps locally with the
CI arguments (`RATCHET_BASE_REV=origin/develop`, develop `e20e9f52ea94`) pinned
the real failure — it was **not** the vulture per-identity ledger:

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **pass** (1326 reviewed identities, no delta)
- `check-shipped-surface-truth.py` → **pass**
- `check-ratchet-provenance.py` → **FAIL** at the delegated trusted-base
  adapters, because `maistro.runs.admission_identity` (an inactive contract
  leaf merged to develop by PR #1936 / auto-#1851) is present in the tree but
  banked in neither `quality/reachability-baseline.json` nor
  `quality/reachability-dispositions.json`.

A fresh reachability scan executed **at the base itself** (`/tmp/base-check`,
commit `e20e9f52e`) yields 169 unreachable modules against its own 168-row
ledger — i.e. the residual originates on develop, not on this branch.

Repro: `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability-provenance.py`

```
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.runs.admission_identity: current unreachable module missing from candidate baseline   (fixed below)
```

## Fixed in this round

1. **Committed unresolved merge-conflict markers** — `docs/research/README.md`
   carried three `<<<<<<< HEAD`/`>>>>>>> fad17a87c` blocks inside the merge
   commit `7de64585c`. `scripts/check-merge-markers.py` had not been run on
   this branch. Resolved by unioning both sides (index rows for #881 *and*
   #882; 1 GRADUATE / 7 INCUBATE disposition summary; the M8-A evidence-index
   paragraph). Gate now passes.

2. **Reachability banked the reviewed identity** (the failing gate's own
   instructed remedy): `maistro.runs.admission_identity` added to
   `quality/reachability-baseline.json` and to
   `quality/reachability-dispositions.json` (LIBRARY group
   `runs-admission-identity-leaf`, subsystem `Run / NodeRun / Attempt
   lifecycle`), matching the module's own "inactive contract leaf" contract
   (#1851, parent #1845). This mirrors the fix-forward commit `96e915a21`
   (auto-16) which hit the identical structural state.

3. **Convergence matrix made to agree with its own census**: banning the
   identity moves the census, so the `Run / NodeRun / Attempt lifecycle` row's
   Unreachable cell `none` → `few` in `docs/architecture/CONVERGENCE-MATRIX.md`
   (`check-convergence-matrix.py` now green).

4. **Suite inventory note updated**: the new
   `.github/workflows/formal-conformance-nightly.yml` adds one Postgres
   service, which parametrizes one more node of
   `tests/test_postgres_health_checks.py` — recorded as `tests/: +1` in
   `docs/testing/inventory-notes/881-execution-lifecycle-state-machine.md`
   (`check-suite-inventory.py` green after the update; the drift was real and
   not develop-caused: base collects 5627, branch collects 5628).

## Validation executed locally (all green unless noted)

- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run mypy <all ten src dirs>` — no issues in 1066 files
- `python scripts/check-merge-markers.py`
- `python scripts/check-suite-inventory.py`
- live-PG run: dedicated pgvector:pg18 container + `alembic upgrade head`;
  `pytest formal/models/test_execution_lifecycle_state.py -v --timeout=600
  --hypothesis-seed=0` → **3 passed in 9.8 s**
- formal-conformance PR policy: `check-m1-convergence-freeze.py --base
  e20e9f52e`, `check-formal-oracle-independence.py --base e20e9f52e` → pass
- convergence/citation gates: `check-convergence-matrix.py`,
  `check-citation-status.py`, `check-reachability-dispositions.py`,
  `check-security-inventory.py`, `check_ac_state_impl.py` → pass

## Residual (cannot be fixed from this branch)

- `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` still find the identity
  **absent from the trusted base** (`e20e9f52e`) with **no already-landed
  authorization** for it. `load_authorizations` reads grants from the base
  (two-merge rule), so this branch cannot self-approve the tolerance, and
  wiring the module into production to dodge the "unreachable" label is
  #1851's separately-reviewed consumer work — faking it would be a
  self-approval, not a repair. The residual clears once develop absorbs the
  banked identity (i.e. when this branch merges); auto-16's `96e915a21`
  documents the identical sequencing.

No `quality/vulture-baseline.json` or grant edits were made: the vulture step
passes unchanged with CI's exact arguments, and no existing identity was
eliminated.

---
inventory-delta:
  tests/: +8
---
# auto-374-repair-ci

Repair-round record for the #374 lane's CI findings, with the corpus-level
reconciliation the repair required.

## What failed, and what the repair was

Three hosted findings at 608f02237 (registry `test` job, quality gate,
coverage gate) were reproduced locally at the merged head and repaired:

1. **registry `test` job** — `tests/test_ratchet_base_rev_policy.py` (2 node
   IDs) failed because `.github/workflows/registry.yml` fell through to a bare
   `github.event.before` for the #374 provenance gate's `RATCHET_BASE_REV`. A
   topic branch's `before` is its own previous tip and any rebase orphans it.
   The expression now uses the guarded chain the other three workflows pin,
   and the repo-wide policy tests pass (13/13).

2. **Coverage gate (diff coverage)** — three files measured below the 90/80
   per-file floor: `maistro_registry/citations.py` at 0% (its exercising suite
   lives in the root `tests/`, which the registry producer never ran under its
   `--source`), `scripts/check-citation-status.py` at 88.9% (guard branches),
   `scripts/check-model-egress.py` at 47.1% (cold sibling-loader path).
   Repairs: the registry producer now names `tests/test_check_citation_status.py`
   alongside the package suite; six parser-guard tests were added; the
   provably unreachable `if not cells` split guard was removed (`str.split`
   never returns an empty list); two sibling-loader tests were added.

3. **Quality gate (acceptance-state ratchet)** — `specs_implementing_nothing`
   measured 93 against a ceiling of 76 folded at base: the #374 waves had
   emptied `implements:` on 17 specs whose only decision is itself Proposed or
   Deprecated. The reconciliation restores `implements:` on those 17 and moves
   each spec's own status back to `Proposed` with a reasoned `history:`
   entry — the lifecycle machine's sanctioned backwards-with-reason move
   (precedent: SPEC-208's M0 evidence reconciliation). `citations.py` holds
   only *active*-source documents to the authority rule, so a Proposed spec
   naming a Proposed decision is exactly the allowed pairing, and the wave
   prose disclaimers stay in place and still asserted. Without it the only
   alternatives were fabricating acceptances of decisions whose own text
   says they are unshipped (ADR-058: "dead scaffold"), or leaving a required
   check red. The three Deprecated-target specs' stale "status is left
   unchanged" convergence notes were rewritten to record the correction.
   Measured after: all counters sit exactly on the base ceilings
   (`check-ac-state.py --run-tests --ratchet` → OK), and the branch's own
   note `quality/ac-state-notes/auto-374.json` banks the measurement.

## Test delta (+8, this note)

- `tests/test_check_citation_status.py` +6: marker absent, header+separator
  only, missing governing columns, truncated body row, and absent matrix file
  — the guard branches of `_matrix_references`/`_matrix_problems`.
- `tests/test_check_model_egress.py` +2: `_load_direct_effects` cold
  load (the path every in-suite import skips because an alphabetically
  earlier module caches the sibling first) and its failed-load cleanup.

No validation-result change beyond the repaired gates themselves.

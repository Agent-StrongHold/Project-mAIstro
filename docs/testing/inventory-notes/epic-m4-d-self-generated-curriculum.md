---
inventory-delta:
  packages/maistro-evolve/tests: +31
---

# epic-m4-d-self-generated-curriculum

Implements the M4-D slice for #24 (SPEC-282): proposer/solver-generated
challenges admitted only behind protected validity gates, and curriculum
practice signal structurally barred from external-evaluation scoring.

New suite `packages/maistro-evolve/tests/test_curriculum.py` (+27, module marked
`@pytest.mark.contract("behavioral")` per ADR-032):

- `TestProtectedGates`: all-gates admission; missing solver / baseline /
  reference solution fail closed (`executed=False`); unsatisfiable draft
  refused by its own reference solution; wrong independent-solver answer
  blocks admission; sync solver seam; vacuous verifier caught by baseline
  discrimination alone; crash containment for solver/verifier exceptions;
  malformed drafts (whitespace statement, non-callable verifier) refused;
  non-`str` solver answers refused.
- `TestCurriculumStore`: only admitted items enter the store; refusals are
  recorded and counted (`summary()`, `rejected`); item provenance pinned to
  `self-generated`; rebranding an item raises; reserved-namespace constants
  pinned.
- `TestGenerateCurriculum`: no proposer raises (never fabricate); a proposer
  crash skips the round and is recorded; a non-draft proposer return is
  recorded, not crashed; degenerate batches admit nothing; async proposer
  awaited; non-positive rounds refused; `submit` refuses non-draft values.
- `TestAdmissionDecisionShape`: empty/partial outcome tuples never admit;
  unknown-gate lookup returns `None`.

Existing-suite additions:

- `tests/test_fitness.py` (+3): `self_generated/…` keys fail the hard gate
  (named in failures) even alongside passing external evidence; a genome
  scored only on curriculum items cannot breed ("no external benchmarks
  evaluated", total 0); curriculum scores are excluded from the weighted eval
  score and its renormalisation (0.5 external evidence is not lifted to
  ~0.75 by a perfect practice score).
- `tests/test_harness.py` (+1): `EvalHarness.register_benchmark` refuses the
  reserved `self_generated/` namespace on both fidelity tiers and registers
  nothing.

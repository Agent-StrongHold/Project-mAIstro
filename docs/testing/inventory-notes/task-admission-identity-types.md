---
inventory-delta:
  packages/maistro-core/tests: +73
---

# #1851 root-admission identity types evidence

Adds the inactive contract module
`packages/maistro-core/src/maistro/runs/admission_identity.py`
(`CanonicalJsonObject`, admission ticket/envelope/binding/record DTOs, claim
and mutation result variants, `AdmissionAssessment`) with its contract test
suite `packages/maistro-core/tests/runs/test_root_admission_identity.py`. No
production module imports the new module in this leaf, and
`maistro.runs.__init__` is unchanged, so no other suite moves.

Collected node IDs on `packages/maistro-core/tests`: 12749 before, 12822 after
(`pytest --collect-only -q`), net **+73** — the new file only; it covers
canonical-JSON normalization/rejection, DTO freezing, the scope+generation+
owner fencing conjunction, binding/acknowledgement invariants, legacy-record
shape, parameterized constructor rejection, result/snapshot agreement, and
owner-token repr omission.

Focused validation at this leaf: 73 passed, ruff check/format clean, mypy
strict clean on the module.

## CI-repair round (merge-queue evaluation at 46af4b5f6f2e)

The merge queue blocked on four checks with two root causes, both expected
drift from shipping an inactive contract leaf:

- **exact-debt-ledger + Quality-gate vulture step:** the scan surfaced 9 new
  `pydantic-declarative-field` identities (the two envelope snapshot fields,
  both `format_version` discriminators, five `AdmissionAssessment` members).
  Banking them in `quality/vulture-baseline.json` cannot pass the gate —
  `ratchet_provenance.load_authorizations` reads grants **from the merge
  base**, which predates the module, so the identities are unauthorizable in
  this branch by construction. Repaired the way the repo already handles
  contract-first surfaces (CampaignSelector, the learning lifecycle, the
  HarnessTargetKind/EvalMethod members): scanner-input references in
  `packages/maistro-core/src/_vulture_whitelist.py`, with the rationale
  inline. The ledger and `ratchet-authorizations.json` are untouched; the
  scan returns to exactly the trusted 1342 identities. When the #1845
  consumer lands, these references should be deleted in the same change.
- **`test` + Coverage `combine`:** `maistro.runs.admission_identity` was
  newly unreachable. Baselined it in `quality/reachability-baseline.json`
  and dispositioned it CONNECT (group `runs-root-admission-contracts`,
  subsystem "Run / NodeRun / Attempt lifecycle") naming the #1845 admission
  backend as the root that will reach it; the gate enforces pruning the
  entry the moment that consumer lands, so the record cannot outlive the
  wiring.

Re-run locally with CI's exact invocations: `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (1342
reviewed identities → 1342 findings, exit 0), `check-reachability.py` (175
unreachable, exit 0), `check-reachability-dispositions.py` (50 groups cover
all 175, exit 0), the three previously failing tests
(`test_baseline_matches_the_tree`,
`test_the_committed_baseline_passes_the_gate_it_now_carries`,
`test_the_baseline_is_exactly_the_unreachable_set`) plus the full 38-test
reachability pair, ruff check/format, and mypy (no new errors vs the
pre-existing 5 `maistro_bootstrap` import-not-found). No test files moved:
inventory re-checked at 12833 collected node IDs on
`packages/maistro-core/tests`, delta unchanged (+73).

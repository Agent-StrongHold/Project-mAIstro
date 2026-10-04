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
strict clean on the module. Full quality gates (vulture/reachability baseline)
remain intentionally blocked until the separately scoped #1845 integration
lands the runtime consumer; no baseline entries or grants were added.

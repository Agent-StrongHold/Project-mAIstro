---
inventory-delta:
  packages/maistro-core/tests: +58
---

# P1a Attempt cancellation-cause model (#1884)

Base: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
Pre-change model blob: `0de6b8ed9dedc87d590b39019cb0b0431e6259a2`.
Initial candidate model blob: `f7edb60a91f9b5592e2b0dcd8cb0dc309a510e09`.
Schema/registration repair model blob: `7d188bfded13ae31b22b4561ed593bdb8708ee78`.

Adds 58 collected cases in `test_attempt_cancellation_cause_model.py`:
14 missing/null cases across all physical statuses, 14 typed-cause/status
cases, 13 invalid-wire cases, three assignment-freeze cases, one exact legacy
payload case, four retained-lease shapes, three nested-serialization cases,
one unchanged-lifecycle guard, one public in-memory creation/claim guard,
two schema-mode cases, one nested-model/TypeAdapter schema case and one
schema-generation/runtime-serialization noninterference case.

The independently frozen legacy JSON was checked against the complete original
model file before testing the candidate. Both file copies were verified with
Git blob hashes. The wrap serializer removes only an unknown cause and preserves
other null evidence. Its class-body registration calls the real Pydantic decorator;
there is no dummy consumer, suppression, gate change or ledger exception.
The JSON-schema hook preserves the declared field schema while leaving runtime
serialization and nested field schemas intact.

## Isolated preflight, not repository or persistence evidence

Original candidate: Python 3.13.5 / Pydantic 2.13.4, 52 pure model cases passed;
the two lifecycle/store cases were deselected because this environment has no
full repository checkout. The same isolated suite against the pre-change blob
failed 27 cases. Independent initial mutations failed as expected: default
RECOVERED (16), dropping all nulls (4), removing the status guard (12).
These counts describe that initial candidate, not subsequent revisions.

Schema/registration repair: the expanded isolated suite passes 56 cases with
the same two integration cases deselected. Restoring the schema-losing serializer
makes exactly the direct serialization-schema and nested-schema regressions fail:
2 failed, 54 passed, 2 deselected. The fixed model was restored and rerun green.
The actual complete model file was loaded under its module name, not replaced
with a substitute implementation. Repository tests, unchanged quality gates and
both production-default guards still require exact-head GitHub Actions evidence.

This is shape/default-invariance work only. No writer, cancellation default,
reclaim predicate, lifecycle store, reconciliation policy, SQL schema, activation
or rollout changes. Unknown historical payloads are not upgraded. Parent #232
and #1151, backend codec proof #1885, and later dedicated writers remain open.

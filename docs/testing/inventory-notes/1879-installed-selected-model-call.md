---
inventory-delta:
  tests/: +81
---

# #1879 the selected completed model-call validator

`tests/release/test_installed_workspace_request_chain.py` (new file, 81 node
IDs) pins `validate_model_call` in
`scripts/installed_workspace_proof_contract.py` (extending the #1878 envelope
module's shared parser/pointer/Report/`MODEL_CALL_SCHEMA_PATH` machinery — no
parallel helper) against
`docs/testing/installed-workspace-model-call.schema.json` (new): one pure
internal-consistency validator for exactly one selected completed model
Invocation, its original physical dispatch, and the originating
request/Run/NodeRun/Attempt records.

`TestSchemaStrictness` covers the exact v1 shape: extra fields rejected at
every object, missing objects, blank structural IDs, `schema_version` literal-1
(including Python `True`), attempt ordinal as a positive integer, blank usage
units, negative units/cost, and the status split that keeps a misspelled state
(SCHEMA_INVALID) distinguishable from the four known non-completed canonical
states (UNSUPPORTED_INVOCATION_STATE). `TestReportShapeAndPurity` pins the
shared versioned Report in structural mode, validator purity (no mutation, no
synthesized completion), determinism, the envelope's duplicate-key parser
(INVALID_JSON before any join rule), and that the selected-call error-code
vocabulary is closed and separate from the envelope's pinned `ERROR_CODES`.

`TestInvocationState` and `TestOrderedJoins` give one mutation assertion per
ordered invariant — state first, then request→Run identity, Run scope/actor,
NodeRun, Attempt, Invocation links, Binding scope, dispatch link,
provider/model, response, usage — each also pinning the neighbor check it must
precede, so spliced records report the first contract-ordered failure at its
JSON pointer. `TestUsageProvenance` pins the iff-rule (usage null exactly when
`usage_provenance.source` is unavailable; nonblank `evidence_ref` otherwise;
no cost fabricated when canonical `cost_cents` is null).

`TestCompletedEffectReuse` validates one unchanged selected-call object twice —
the original physical dispatch, then a retry reusing the completed effect —
and asserts both passes are byte-identical reports with the record never
rewritten: no new Invocation, dispatch, or counters are invented, and the
object's NodeRun/Attempt stay the original effect's provenance (logical_effect
dedup may span NodeRuns). All of it is consistency proof only, not provider
authenticity, turn accounting, Warden/Sentinel enforcement, restart proof, or
#87 closure.

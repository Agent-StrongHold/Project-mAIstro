---
inventory-delta:
  tests/: +87
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

## Repair: the validator's call path (CI-repair round)

The first cut shipped the validator as unreachable-from-any-entry-point
tooling: it is a pure helper the release tests importlib-load, no workflow
named its file, and nothing imports it — so `check-reachability.py`,
`check-reachability-provenance.py`, the reachability suite, and every CI job
running them (exact-debt-ledger, the quality gate, the root-suite test and
coverage producers) failed on `@tool/installed_workspace_proof_contract` as
newly-unreachable debt. The baseline could not absorb it: the two-merge rule
reads `quality/ratchet-authorizations.json` from the merge base, so a
same-PR authorization is self-approval by definition. The repair gives the
module the call path the ratchet recognizes, the same one #1878's validator
was wired with:

- `scripts/installed_workspace_proof_contract.py` gains a thin fail-closed
  CLI (`main`: 0 valid, 1 invalid report — INVALID_JSON included, 2 CLI
  misuse; document text goes through the shared duplicate-key parser). The
  pure `validate_model_call` API is unchanged.
- `quality.yml` quality-gate step `selected model-call validator fails
  closed via CLI (#1879)` builds a synthetic, fully consistent selected-call
  document, runs the real CLI (structural exit 0, `"valid": true`), then
  splices the dispatch onto a foreign Invocation and asserts the process
  exits 1 with `DISPATCH_LINK_MISMATCH` — the validator's fail-closed
  headline exercised end to end on every PR. Naming the file is also what
  makes the reachability ratchet see it as wired; consistency proof only,
  no model call, no credentials.
- `tests/test_check_reachability.py::test_the_gate_scripts_themselves_are_reachable`
  now lists the module, so removing the workflow step fails a test, not just
  the gate.
- `TestCli` (+6 node IDs, delta above 81 -> 87) covers the CLI in-process
  (valid/spliced/INVALID_JSON/missing file/arg count) plus one real-process
  subprocess run covering the `__main__` guard the workflow relies on.
  No pytest assertion was replaced; the added cases pin the process entry
  the in-process suite could not see.

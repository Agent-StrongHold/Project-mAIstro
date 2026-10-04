---
inventory-delta:
  tests/: +96
---

# #1878 the installed-workspace proof envelope validates fail-closed

`tests/release/test_installed_workspace_proof_schema.py` (new file, 96 node
IDs) pins `scripts/validate-installed-workspace-proof.py` and
`scripts/installed_workspace_proof_contract.py` (both new) against
`docs/testing/installed-workspace-proof.schema.json` (new): one offline
validator that separates structurally valid evidence from a complete observed
release-proof envelope, with all five scenario families mandatory in both
modes.

`TestCloseoutSemantics` pins the split the issue exists for: FAIL/BLOCKED/
NOT_RUN rows are legitimate structural evidence (structural mode exits 0) and
fail closeout by exact row pointer; a synthetic all-PASS bundle is likewise
structural and rejected at closeout only by SYNTHETIC_NOT_CLOSEOUT; a family
can never be NOT_APPLICABLE; a missing family fails in both modes; the
reviewed profile defines exactly three properties — there is no waiver switch
— and an injected `waive_families` key is rejected.

`TestBrowserApplicability` pins the applicability join against the
independently supplied profile: NOT_APPLICABLE exactly when the profile says
browser login does not apply, in both modes, so a bundle can never vote
itself out of a subcheck. `TestSchemaRejections` covers the shape floor —
duplicate JSON keys (INVALID_JSON, not last-wins), extra properties, wrong
types, blank/whitespace-only IDs, malformed hex, unknown families, and the
PASS/null-reason/nonempty-evidence outcome rules. `TestEvidenceFiles` covers
the byte-level checks: hash bytes not reformatted JSON, missing/unlisted
files, the listing boundary (results.json required; manifest.json and the
external profile forbidden), duplicate listings, and path safety including a
symlink escape that is reported WITHOUT the outside file ever being read.

`TestDeterminism` pins the report contract: stop at the first failing stage,
diagnostics sorted by `(path, code)` with exact duplicates collapsed, exact
report shape, and no file contents or secrets in diagnostics.
`TestContractHelpers` unit-pins the shared parser/Report; `TestCli` runs the
real process for exit codes 0/1/2 with usage diagnostics on stderr and an
empty stdout for misuse. Envelope validation never asserts that a run
occurred, that evidence is authentic, or that live security/provider behavior
passed; the observed all-PASS fixtures are correctly hashed, which is all the
envelope check claims about them.

Repair addendum (this branch): the first cut left both new scripts
unreachable-from-any-entry-point — release tooling nothing imports and no
workflow named — so `check-reachability.py`,
`check-reachability-provenance.py` and the four reachability tests failed, and
the coverage producer (which runs the root suite) failed with them. Baseline
could not absorb them: the two-merge rule reads grants from the merge base, so
a same-PR authorization is self-approval by definition. The repair wires the
validator the way the ratchet recognizes: a `quality.yml` quality-gate step
(`installed proof envelope validator fails closed via CLI (#1878)`) builds a
synthetic, correctly hashed envelope and asserts through the real process CLI
that structural mode exits 0 with `"valid": true` while closeout exits 1 with
`SYNTHETIC_NOT_CLOSEOUT` — the contract's fail-closed headline, now exercised
end to end on every PR. The sibling contract module is reached through the
validator's own import of it. `tests/test_check_reachability.py::
test_the_gate_scripts_themselves_are_reachable` now lists the validator so
removing the workflow step fails a test, not just the gate. Test count
unchanged (+0); the workflow step replaces no pytest assertion — `TestCli`
already covered exit codes in-process, this adds the real-process smoke the
suite cannot give.

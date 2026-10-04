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

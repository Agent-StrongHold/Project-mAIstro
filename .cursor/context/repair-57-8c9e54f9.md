# Issue #57 repair — frozen scope 2026-10-20

Assigned worktree `/home/dev/Git/wt/auto-57`, starting HEAD `63ad4b044eb0cf6b32210419bd6c7b3d71a76bf8`, base/MERGE_HEAD `e20e9f52ea94b393184f210cc9379f9f693f13d0`.

Snapshot: ONLY issue #57; frozen dispatch-context.json and prior job result; interrupted merge and its existing six paths (governed_invocation.py conflict, admission_identity.py, root-admission tests, inventory note, repair-1851 note, vulture ledger); #57 tool-contract implementation and adjacent tests; SECURITY.md claim drift; exact-vulture CI repair. No GitHub mutation or new issue work.

At entry merge already active, one UU file. Preserved work in job directory as incoming-57.patch and incoming-57-index.patch. Assumption: incoming admission-identity files are develop merge content, not new #57 scope; preserve them. No check-*.log files present in supplied job directory at entry. Prior result records #847 open and remote CI unverified; revalidate locally, do not infer completion.

Plan: read architecture/ADRs and acceptance evidence; resolve conflict preserving both sides, reconcile inaccurate security claim, run actual exact-vulture scan and amend only reviewed retained identities if needed; focused tests and gates, commit repair/merge. External criterion #847 remains owner-held unless frozen evidence proves closure.

## Inspection / merge repair
- Read repository instructions/docs map and accepted ADR-081226-6b46, ADR-050/051, ADR-004, ADR-081226-7248, ADR-081226-a66b. Canonical Invocation/Run/event authorities preserved. ADR-004 amendment explicitly removes unenforced spec fields; no reintroduction.
- SECURITY.md:35 is already corrected at starting HEAD: governed contracts construct registry, Sentinel reversibility approval integration remains a limitation. Prior claim-drift finding is not reproducible; no cosmetic change.
- Frozen dispatch #57 has twelve criteria, #847 remains open. No check-*.log files supplied. Historical REPAIR-NOTES-57.md reviewed, not promoted to current validation.
- Conflict is a modify/delete-style hunk around existing reconciliation methods; retained HEAD reconcile/reconcile_with_provider/_append_reconciliation_event alongside expected-effect methods and incoming develop context. Removed only conflict markers. Existing tests for both behaviors will be executed.
- Incoming ledger additions are five AdmissionAssessment enum constants from develop, preserve unless actual scanner proves otherwise. No issue #1851 redesign attempted.

## Validation checkpoint
- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: passed, 3368 files. Both diff whitespace checks passed.
- Core focused production/adjacent tests (tools, capabilities including both reconciliation wrappers, Agent/ReAct/builders/artificer/spec/audit, incoming root admission tests): 1562 passed, 11 skipped, one existing mock coroutine warning; repair-core.log.
- Exact vulture command pre-merge commit: 1322 findings, 0 unclassified, 0 never_allowlist, but provenance compared HEAD's merge-base fad17a87c (old base): reported five incoming develop enums new and four removed branch identities. Explicit RATCHET_BASE_REV=e20e9f52 still resolves merge-base against pre-merge HEAD, so same failure; no ledger mutation is justified. Re-run after completing preserved merge so the trusted base includes develop's already-banked enums.
- Workflow lookup included nonexistent architecture-convergence-ratchet.yml: not found; skipped. Actual vulture-ratchet.yml exact-debt-ledger command read. All refs passed to commands resolve locally.

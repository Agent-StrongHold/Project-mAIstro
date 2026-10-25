# Issue #1893 bounded repair at 7c464c76

## Frozen scope

One item: issue #1893, branch `auto-1893`, starting head
`7c464c760a6f0dad0a6e3ac58dd85599656095bc`, assigned develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`.
The worktree was clean. No incoming changes require salvage.
Inspect only the admission codec, immutable identity types, their focused tests,
adjacent admission persistence/JSON utilities, relevant ADRs and CI gates.
The intended changed file is this validation report; change production/tests or
inventory only if reproduced evidence requires a scoped repair. No ledger or
grant change is presumed necessary. No remote mutation or new dispatch.

## Initial evidence and assumptions

The supplied job's check-0 through check-4 logs report dependency sync, clean
ruff lint/format, 201 passing focused tests with 3 skips, and a matching core
suite inventory (16466 nodes). These are driver observations, not fresh worker
validation. PostgreSQL skips do not establish durability.

The dispatch supplies `test: failure` without a current failure traceback.
Assumption: reproduce the focused package behavior and named gates before
considering a code change. Prior reachability authorization claims remain
untrusted until the provenance gate is executed. Existing unreachable B2 code
must not be wired to a live consumer merely to silence a gate: the issue forbids
activation and assigns that consumer to another leaf.

## Results

Fresh execution reproduced the structural blocker:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed findings, zero unclassified. No Vulture ledger repair is justified.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`: exit 1. Both admission modules are NEW unreachable modules and NEW dispositions without trusted-base authorization (169 -> 171). All other constituent gates passed.
- `origin/develop` and the merge base both resolve to the assigned base `435dc1937e0407ab4de198ffcced49860bb14ad2`. There is no local develop-sync conflict to resolve. No fetch or GitHub request was made.
- Source search finds no production codec caller: only the codec imports the DTO, plus the Vulture whitelist's DTO import. Package exports/test imports cannot establish reachability.

This is reachability provenance debt, not Vulture debt. The explicit Vulture
ledger exception cannot authorize a reachability ledger/grant edit. Continue
only bounded validation and record a blocked handoff; do not start another
repair item or repeat the same failed gate.

Fresh focused checks also passed:

- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, two files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-c1720c1b-focused.xml`: 201 passed, 3 skipped. The XML records all 204 collected nodes. Both required PostgreSQL environment variables are unset; no live database proof is claimed.

Read accepted ADR-081426-1f7c and ADR-082526-7f02. Immutable admission
provenance must not become dispatch identity or execution authority. The codec
remains a pure representation leaf; preserving that boundary takes precedence
over adding a fake caller to satisfy reachability. No competing execution,
authorization, scheduler, Goal store or event authority was added.

Additional executed checks:

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped, 6 warnings. Warnings are aiosqlite worker callbacks after event-loop closure in adjacent SQLite tests; no failing node reproduced the dispatched CI failure.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.

Read the supplied prior result artifact: it reports the same blocked state at
this starting head. Fresh results above, not that prior assertion, determine
this handoff.

## Acceptance assessment

The focused execution covers all pure prospective tests in the issue:

| Criterion | Evidence at this source head |
| --- | --- |
| Immutable DTOs, fresh flat SQL mappings and v2 snapshot preservation | `test_v2_round_trip_preserves_all_snapshot_bytes` in three states, `test_encode_returns_a_fresh_flat_mapping`, adjacent frozen DTO tests passed. Independent task/Run pair assertions pin migration-055 shape rather than just encoder/decoder agreement. |
| Strict storage UUID hex, timestamps, header agreement and safe typed errors | Owner/generation hex, scalar mismatch/range, invalid-schema/format, error-scope and suppressed-chain tests passed. |
| Legacy bound/unbound/partial/receipt-only remain distinct; no identity invention | Legacy classification, expired-header, receipt-only, missing-receipt and unreadable-evidence tests passed. |
| Preserve header expiry/fingerprint despite snapshot/binding failure | Both explicitly named header-preservation tests passed; codec takes no clock or incoming fingerprint. |
| Strict snapshot JSON and arbitrary permitted nested evidence | Duplicate/nonobject/bare nonfinite, nesting, numeric precision, Unicode, tagged nonfinite and unchanged fingerprint tests passed at the representation boundary. |
| Raw and production pools read identical migrated TEXT | **UNVERIFIED this round:** all three PostgreSQL cases skipped. No migrated database, session IDs or final SQL row counts claimed. |
| Evidence serializers and model materialization; original-model fingerprint; Run JSONB object insertion | **UNVERIFIED end to end:** these focused fixtures hand-build tag objects, not actual authorized admission models. No live codec consumer exists. |
| Named SQL field mapping, no SELECT ordering dependency | Source review of `encode_admission_record` and named-column decode; pure mapping assertions passed. Database constraint enforcement remains unverified this round. |
| No SQL mutation, HTTP mapping, queue/assessment/claim or policy change in B2 | Codec source reviewed; it only accepts/returns mappings and immutable DTOs. No production source changed in this repair. Consumer expiry/409 precedence is explicitly outside B2. |
| Real principals, authorized Workspace/Project, registered Graph kinds | **UNVERIFIED:** DTO fixture IDs do not establish authorization or canonical execution. |
| Required CI, reachability and disposition provenance | **FAILED:** provenance gate rejects two modules and their dispositions. Full unchanged required CI and the reported `test: failure` are **UNVERIFIED**; scoped passing tests are not full CI. |
| Inventory, lint/format and applicable mypy | Passed as recorded above; no test addition, deletion or inventory delta this round. |
| Coordination and activation approval | **UNVERIFIED:** local lane assignment authorizes repair/evidence only, not independent integration or rollout. |

No pre-fix or mutation success is claimed: no source/test repair was made.
Injected failure boundaries in the existing tests are raw mapping fields and
snapshot TEXT, not transactions or crash/dispatch boundaries.

## Blocked handoff

Only `docs/testing/issue-1893-repair-7c464c76.md` changed. No source, test,
whitelist, ledger, grant or gate changed. Existing work was preserved.

**BLOCKED:** `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` contain admission debt that
fails trusted-base authorization. Resolution requires the integration owner
to reconcile the staged inactive leaf with the two-merge reachability policy
outside this lane's permissions. Supply the exact current-head CI failing
node/traceback before requesting another test repair. Do not repeatedly
redispatch unchanged green codec tests as if they can clear this blocker.

Progress: checked 1; done 0 repairs; skipped 0 items; errors 1 reproduced
provenance blocker; next: integration-owner authorization/coordination decision
and concrete CI failure evidence. This evidence commit is not merge approval.

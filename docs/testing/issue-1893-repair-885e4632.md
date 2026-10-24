# Issue #1893 repair — job 885e4632

## Frozen scope

- Issue: #1893 only; assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `2f7bf42a328a3e6c9d0dfe9dfae40fe42e49ba20` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Initial working tree clean. No incoming uncommitted work to salvage.
- Evidence: job `885e463231f74781b46c8bc876974c13` dispatch-context.json and check-0 through check-4 logs; supplied prior result `eafe274f83a143599d44815c673fc3d2/result.json` if present.
- Implementation/test scope: `maistro/tasks/admission_codec.py`, `maistro/runs/admission_identity.py`, adjacent `test_admission_codec.py` and `test_root_admission_identity.py`; inspect relevant ADRs, CI workflows and existing reachability ledger delta without changing them. Vulture ledger edits only if the explicitly requested scanner produces real evidence. This report is the only planned new file unless reproduced failures justify repair.
- Ambiguity: dispatch says `test: failure` without a failing node. Assume reproduction is required, not proof of a code defect. Prior readiness claims will not be counted as this run's evidence.
- Staged codec readiness is not activation/merge authorization. No new runtime wiring, policy, scheduler or authorization path is authorized by this leaf.

## Progress

- Read all five supplied driver logs: dependency sync, Ruff check/format and suite inventory passed; focused tests were 201 passed, 3 skipped. No failing test traceback is present. The skipped PostgreSQL legs are not durability proof.
- Read the complete codec, immutable DTO implementation and codec tests. Source explicitly marks both modules inactive; codec performs mapping/DTO conversion only. Existing PG tests use independent real pools but fixture identities, not authorized admission or Run persistence.
- Read prior result and report as historical evidence only: previous blocker is trusted-base reachability provenance, not Vulture identities. This will be reproduced once against the frozen supplied base; no gate edits or invented production consumer are permitted.
- CI workflow confirms exact Vulture arguments and trusted-base provenance step. No code defect demonstrated so far.
- Fresh `uv sync --locked --extra dev` and exact Vulture scan passed: 1323 findings, zero unclassified. No Vulture amendment is warranted.
- Fresh `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` FAILED (exit 1): two NEW unreachable modules and two NEW dispositions without already-landed authorization (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`). Other provenance sub-gates passed. Local origin/develop resolves to the supplied base; no sync conflict exists. This blocker cannot be repaired by the Vulture-only ledger exception.
- Read accepted ADR-081226-a66b, ADR-081626-f383, ADR-082226-5104 and adjacent identity tests. No competing lifecycle, execution fencing authority or durable store is authorized or introduced.
- Production source search found only DTO import from codec and whitelist import of AdmissionAssessment; no real consumer. An initial overly restrictive search glob produced no matches, corrected once. Optional `.github/workflows/test.yml` not found; skipped; actual pytest workflows identified from local files.
- Captured PR bodies #1325/#1855/#1945/#2109 inspected once with their captured SHAs, not accepted as current proof. No captured failing check output was found by the check-run extraction. #2109 concerns CodeQL alert numbers, not this implementation scope.
- Lane-local PG container verified running (`auto-1893-pg`, pgvector/pg18, port 15498). Initial connection as container root failed because POSTGRES_USER is unset; no DB modified. Used the container's PostgreSQL OS account and a new job-specific disposable DB only.
- Fresh root Ruff lint and format checks passed (3277 files); targeted mypy on the two source modules passed.
- Verified PostgreSQL 18.6 and absence of `maistro_1893_885e4632`, then created that DB. `uv run alembic upgrade head` passed the real 001→062 chain; both nonempty test DSNs and DATABASE_URL targeted that DB. `MAISTRO_REQUIRE_PG_LEGS=1` required real PG legs. Focused pytest: **204 passed, zero skipped** (1.43s), JUnit plus migration/test logs in this job directory. No existing DB was modified.
- Independent final SQL confirmed migration 062 and zero admission rows. Optional extra query against guessed relation `runs` failed (not found); no mutation resulted. Correct canonical table will be confirmed before any further SQL. This inspection mistake is not a test/migration failure.
- Read actual CI `test` job: it deliberately does not execute the core suite (coverage owns it). It includes unrelated package/frontend/root suites. Generic `test: failure` cannot be attributed to this codec without a failing node/step; complete hosted test job remains UNVERIFIED.

## Executed acceptance

All validation used unchanged source HEAD `2f7bf42a328a3e6c9d0dfe9dfae40fe42e49ba20`. Focused command, with the DB environment described above:

```sh
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/885e463231f74781b46c8bc876974c13/worker-pg-tests.xml
```

204 collected, 204 passed, zero skipped. Production/raw sessions respectively: 21453/21454 (unbound), 21455/21456 (bound), 21457/21458 (acknowledged); all on `maistro_1893_885e4632`, `172.17.0.9/32:5432`. Each state persisted one admission row. Independent final SQL, after confirming the table name in migration 012: **0 task_idempotency rows, 0 canonical_runs rows**, revision 062. DB retained for handoff; no destructive migration/downgrade tests or shared DB changes.

| Criterion | Evidence / limit |
| --- | --- |
| Exact frozen/slotted header, six error codes, named fields and scalar agreement | Complete source inspected; missing-column, scalar mismatch and header validation tests passed. |
| Strict storage UUID .hex, signed timestamps, immutable #1851 constructors | UUID, scalar range/type, identity and variant-constructor tests passed. |
| Fresh flat SQL mapping and snapshot evidence | `test_encode_returns_a_fresh_flat_mapping` and three-state `test_v2_round_trip_preserves_all_snapshot_bytes` passed; independent task_id/run_id assertions match migration 055 CHECK. |
| Legacy bound/unbound/partial distinguished, no guessed identity | Named legacy tests passed, including receipt-only, one-sided, corrupt and pair-without-receipt rows. Reconciliation: immutable AdmissionBinding requires receipt identity; a legacy pair without it fails partial rather than inventing a receipt. |
| Header/full decode separation | Both expiry/fingerprint-preservation tests passed across invalid snapshots/partial binding. No clock or incoming fingerprint accepted; C/F2 precedence behavior is outside B2 and UNVERIFIED. |
| Unknown formats and invalid original data fail closed | Unknown-format laundering, invalid/duplicate/nonobject/bare-nonfinite JSON, numeric loss, nested and Unicode corruption tests passed. |
| Error hygiene | Tests assert typed error, validated scope hash, no raw snapshot/token text, suppressed parsing context. |
| Evidence tags/arbitrary permitted program_context and fingerprint | Tagged nonfinite and exact numeric/Unicode round trips passed; codec preserves stored fingerprint and does not interpret tags. Actual original-model fingerprint computation and model_of/model_of_json materialization are **UNVERIFIED** here: fixtures manually construct tags. |
| Real migrated DB/raw and production pools | Fresh chain 001→062; same DB confirmed via distinct backend sessions; all three real pool tests passed without skips. Escaped surrogate corruption injected into every snapshot TEXT column is rejected through both pools. |
| TEXT SQL field mapping | Live INSERT/SELECT passed through both pools, including paired bound identities. Physical `request` TEXT maps to DTO `request_snapshot`, matching migration 055, not a renamed column. |
| Actual Run json_of INSERT using text::jsonb, object payload | **UNVERIFIED** by this codec suite; it does not persist a Run. No competing persistence path added. |
| Explicit principals, authorized Workspace/Project and registered Graph kinds | **UNVERIFIED**: low-level storage fixtures use identity strings, not admission/auth checks. Not claimed as crash, transaction/admission or dispatch proof. |
| No activation, SQL mutation, HTTP mapping, queue/scope/_assess change | Complete codec inspected: reads mappings and returns DTOs/mappings only. No implementation change in this round. Goal → Graph → Run → NodeRun → Attempt unchanged. |
| Unchanged CI, production reachability and no self-authorized baseline debt | **BLOCKED**: no runtime consumer and trusted-base provenance rejects existing admission module/disposition additions. Full required CI **UNVERIFIED**. |
| Coordination and policy restrictions | Assigned worktree/branch/base retained; captured external comments are evidence only. No merge, push, ownership change, policy choice, activation or closure performed. |

No new regression test or mutation/pre-fix run is claimed: no code defect was reproduced and no tests were changed. Inventory delta note is therefore not required.

## Other commands and outcomes

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two source files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 exact identities, no unclassified findings; no ledger amendment justified.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/tasks -x -q --timeout=60`: PASS, **1918 passed, 310 skipped, 5 warnings** (51.37s). No PG DSNs supplied for this wider smoke run; skips do not prove durability. Warnings are aiosqlite background threads encountering closed event loops in existing test_sqlite_store cases; not attributed to codec or changed speculatively. Log: `worker-adjacent-tests.log` in the assigned job directory.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16466 nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger (1396 production modules, 171 unreachable).
- `uv run python scripts/check-reachability-dispositions.py`: PASS against candidate ledger (50 groups, 171 modules).
- `uv run python scripts/check-promotion-surface.py`: PASS (74 tolerated modules).
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1, reproduced once. Candidate-ledger passes above cannot override trusted-base rejection.
- `git diff --check`: PASS.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-885e4632.md` (this report). No source, tests, inventory, whitelist, quality ledger or grants changed. The requested Vulture check is green; changing it would be cosmetic rather than evidence-backed repair.

Remaining blocker: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` add two unauthorized inactive modules/dispositions. Resolving this needs a separately reviewed prerequisite already landed on the trusted base under the two-merge rule, or separately authorized real consumer integration. This lane cannot grant itself authorization, fake reachability, or expand into parent activation. Preserve the existing work.

Request the exact current failing CI step/node/traceback for `test: failure` before another test-repair assignment. It is unresolved, not disproved by scoped passes. No further unrelated suites or implementation items started.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1 required provenance gate. Next: external prerequisite and current CI traceback. Verdict **BLOCKED**; local documentation commit only, not integration approval.

# Issue #1893 repair validation — 6fbcb022

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head: `6f8e46275e7e2a71e45d214daf906ab68298a5b8`; supplied develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Process only issue #1893. Source/test snapshot: `maistro/tasks/admission_codec.py`, `maistro/runs/admission_identity.py`, their two existing test files, existing B2 documentation, and the supplied changed-file list. CI repair may amend `quality/vulture-baseline.json` only for evidenced retained identities. No other ledger or grant edits authorized.
- Initial worktree clean; no incoming changes to salvage.
- Evidence snapshot: job `6fbcb02240474f4b8325a85d4c8bef3c/dispatch-context.json` and `check-0.log` through `check-4.log`. No GitHub mutations or re-enumeration.

## Initial evidence and assumptions

Driver logs: dependency sync, ruff check, format check, and suite inventory pass; focused tests report 201 passed, 3 skipped. These skipped tests do not establish database acceptance. The reported CI `test: failure` has no failing node in the assignment; reproduce locally before changing code. Prior findings about reachability authorization must be checked against the frozen base, not presumed still true. This round is repair/validation only, not production activation or independent integration approval.

## Reproduced blocker

`origin/develop` resolves to the supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2`. No sync conflict exists.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed identities/findings, zero unclassified. No Vulture ledger repair warranted.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`: exit 1. `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each have unauthorized new unreachable-module and disposition entries (169 -> 171). Other constituent checks passed.

This reproduces the prior blocker independently. A Vulture-only ledger exception cannot authorize reachability edits. Adding a fake runtime caller would violate the inactive-leaf scope. Continue only bounded acceptance validation; final disposition is blocked unless evidence changes. No grant/gate/source repair is justified by this result.

## Focused validation

Fresh commands at the starting source SHA:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, two files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: 201 passed, three PostgreSQL skips.
- PostgreSQL preflight: local socket server is PostgreSQL 18.6; dedicated database `maistro_1893_job6fbcb022` does not exist yet.
- Production-source search for `admission_codec|admission_identity`: only the codec's DTO import and Vulture whitelist import; no runtime consumer.

Read full codec and adjacent codec/DTO tests. The interface is representation-only; synthetic fixture identities cannot prove authorized admission or runtime integration. Read accepted ADR-082526-7f02 (admission provenance immutable; dispatch belongs to Attempt). Initial guessed filename for ADR-081426-1f7c was not found; resolved actual filename with a bounded file lookup before continuing. Read accepted ADR-081426-1f7c in full: runtime mechanics use Attempt identity and cannot become domain execution or permission authority. No reconciliation requires changing the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model.

## Database and adjacent acceptance execution

Created only the dedicated, previously absent disposable database. Exact commands:

```sh
createdb -h /var/run/postgresql -U dev maistro_1893_job6fbcb022
export DATABASE_URL='postgresql://dev@/maistro_1893_job6fbcb022?host=/var/run/postgresql'
export MAISTRO_TEST_PG_DSN="$DATABASE_URL"
export MAISTRO_TEST_DATABASE_URL="$DATABASE_URL"
export MAISTRO_REQUIRE_PG_LEGS=1
uv run alembic upgrade head
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-6fbcb022-pg.xml
```

Real empty-schema migration chain applied through **062**. Focused result: **204 passed, zero skipped**, with 204 collected testcases in the JUnit artifact. No SQLite recreation or fake pool used for the three database cases. Production/raw session PIDs, respectively: unbound **1403160/1403161**, bound **1403162/1403163**, acknowledged **1403164/1403165**. Each pair asserts identical database/server identity and different sessions; each state persisted exactly one admission row. Tests inject corrupt escaped-surrogate TEXT into each snapshot column and assert typed safe rejection through both pools.

Independent final SQL query confirmed revision 062 and **zero rows** in each of `task_idempotency`, `tasks`, `canonical_runs`, `canonical_node_runs`, and `canonical_attempts`. Database retained; no downgrade/destructive migration test run.

Additional commands:

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Without database environment variables, `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped, 5 warnings**. Warnings are aiosqlite worker callbacks after event-loop closure in existing SQLite tests. Skips are not database acceptance.
- `git diff --check`: passed.

## Acceptance matrix and limits

All ten prospective named codec tests executed in the live 204-node run:

| Criterion | Fresh evidence |
| --- | --- |
| Exact immutable v2 DTOs and flat named-column encoding | `test_v2_round_trip_preserves_all_snapshot_bytes` in unbound/bound/acknowledged states, `test_encode_returns_a_fresh_flat_mapping`, DTO immutability tests passed. Bound mapping independently asserts migration-055 task/receipt identity. |
| Storage-only UUID hex, validated signed timestamps and scalar header matching | `test_owner_token_is_hex_at_storage_only`, strict generation tests, invalid scalar tests, header mismatch and constructor rejection tests passed. Source declares frozen/slotted header and required error enum. |
| Safe typed corruption disposition, no raw token/snapshot diagnostics | Duplicate/nonobject/bare nonfinite JSON, deep nesting, lossy decimals, invalid Unicode and owner/generation rejection cases passed, including suppressed exception chains and validated scope. |
| No inferred legacy work identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only and bound-pair-without-receipt rejection, whitespace evidence and completed-at tests passed. |
| Header/full-decode separation | Expired legacy scalar evidence, malformed-snapshot expiry preservation and partial-binding fingerprint preservation tests passed. No clock or request fingerprint enters the codec. |
| Unknown formats fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` passed for seven invalid formats, including mismatched supplied headers. |
| Tagged snapshot evidence and fingerprint preserved | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` and exact/nested/Unicode numeric evidence cases passed at the representation boundary. |
| Raw and production pools read identical TEXT | Three real migrated PostgreSQL cases passed, zero skips, sessions/counts above. |
| No SQL/HTTP/queue/assessment change or competing authority | Source inspection: codec consumes mappings only; no runtime caller. This round changes documentation only. |
| Real model evidence encoding/materialization through `model_of`/`model_of_json`, original-model fingerprinting and Run JSONB object insertion | **UNVERIFIED** by these fixture-based codec tests; no runtime integration is authorized in this leaf. |
| Explicit authorized principals/Workspace/Project/registered Graph admission, consumer inclusive-expiry/409 precedence | **UNVERIFIED**; fixture identity strings prove representation, not admission policy or transactions. |
| Full unchanged required CI and dispatched `test: failure` | **UNVERIFIED**. Focused/adjacent failures not reproduced; exact failing CI node/traceback absent from assignment. Trusted-base provenance definitely fails. |
| Coordination, mergeability and production activation | **UNVERIFIED/BLOCKED**; local repair assignment is not an activation-policy or ownership decision. |

No source/test change or new test was warranted by current evidence; inventory counts unchanged and no inventory-delta note needed. No pre-fix or mutation failure is claimed for this documentation-only round.

## Blocked handoff

Only `docs/testing/issue-1893-repair-6fbcb022.md` changed. No source, tests, whitelist, quality ledger, grant, or gate changed. Provenance rejects `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`; the explicit Vulture exception cannot resolve that separate authorization requirement.

Next: integration owner must resolve reachability under the two-merge trusted-base policy or coordinate an authorized runtime integration slice. Supply the current-head CI `test` traceback before requesting another source repair. Repeating green codec validation against unchanged source/base cannot discharge either gap.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 reproduced provenance blocker. This evidence commit is a blocked handoff, never integration approval.

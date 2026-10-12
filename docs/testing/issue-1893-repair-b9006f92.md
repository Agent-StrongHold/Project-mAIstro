# Issue #1893 — blocked repair handoff b9006f92

## Frozen scope and reconciliation

- Assigned writer: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Tested source: `4939da731a164f8e5ce105263e94ff837a727dc2`.
- Resolved `origin/develop`: `3c761d14db944a727fa0744444bc67cfe36d49f7` (the supplied base).
- One item: #1893, reported `test` failure and exact-debt-ledger repair. Initial tree clean; no salvage or merge conflict. No remote refresh/mutation, consumer activation, ledger/grant/gate changes, or unrelated repair.
- Read repository instructions, codec/identity implementation and adjacent tests, CI workflows, and accepted ADRs 081226-a66b, 082526-7f02, 083126-5e62. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt, immutable admission provenance, and trusted-base authorization. The Vulture-only ledger exception does not authorize reachability policy changes or a fake production caller.
- Only repository change this round is this report. No tests added or removed; no inventory delta. No production defect reproduced, so no speculative code repair.

## Executed checks

Commands had 1200-second validation timeouts. Driver `check-0.log` through `check-4.log` and supplied prior result were inspected, not accepted as substitutes for execution. Artifacts live under `/home/dev/maistro/jobs/b9006f92150f470ab923d055790f4f08/`.

| Command | Fresh result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings / 1323 reviewed identities, zero unclassified. No ledger amendment warranted. |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two unauthorized dispositions. `worker-provenance.log`. |
| `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs` | 201 passed, 3 skipped without PG configuration; not durability proof. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3277 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 collected identities; no duplicate evidence. |

The provenance failures are `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. CI executes the failing command in `.github/workflows/vulture-ratchet.yml:77`. Banking or Vulture edits cannot authorize this debt.

The supplied dispatch snapshot's failed `test` check names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output text/summary, not the tested head. The captured #1945 check failure is exact-debt-ledger at `fcc8b437f209a35aa68a61d6f0a5387414938355`. No assigned-head failing test traceback was supplied. `.github/workflows/ci.yml:574-612` places core in the separate coverage producer; a core pass does not establish the `test` job. That report remains UNRESOLVED, not repaired.

## Fresh real PostgreSQL evidence

Created a new dedicated database using `createdb maistro_1893_b9006f92` on local PostgreSQL 18.6, then executed:

```sh
DATABASE_URL=postgresql:///maistro_1893_b9006f92 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_b9006f92 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_b9006f92 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs \
  --junitxml=/home/dev/maistro/jobs/b9006f92150f470ab923d055790f4f08/worker-live-pg.xml \
  -o junit_family=legacy
```

Real migration chain from empty through **062** passed (`worker-migrations.log`), including migration 055. Focused tests: **204 passed, zero skipped**, 1.51s. No downgrade experiment was performed.

The three two-pool tests record the same database over local Unix sockets (address/port NULL), distinct backend PIDs, and one persisted admission row per case:

| State | Production PID | Raw PID | Persisted admission rows |
| --- | --- | --- | --- |
| unbound | 1513875 | 1513876 | 1 |
| bound | 1513877 | 1513879 | 1 |
| acknowledged | 1513880 | 1513881 | 1 |

The production fixture uses `_register_json_codecs` and non-null `pg_pool`; raw asyncpg reads the same named TEXT columns. Actual INSERTs satisfy the migrated binding CHECK. Tests also inject escaped-surrogate corruption into each snapshot column and require sanitized typed failures through both pools. Final SQL queries confirmed revision 062 and **zero** rows in `task_idempotency`, `canonical_runs`, `canonical_projects`, and `canonical_project_memberships`. The disposable database is retained; no shared database was truncated.

## Acceptance accounting

| Criterion | Evidence / limit |
| --- | --- |
| Exact frozen/slotted header; named mapping; six decode codes; strict signed timestamps and UUID hex; #1851 constructors | Source inspection plus passing focused header, scalar, generation, owner-token, and round-trip tests. |
| Header/full-record separation, mismatch refusal, unsupported format fail-closed | Named prospective header and unknown-format tests execute successfully; no clock or incoming fingerprint accepted. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run; no invented identity | Passing legacy tests, including absent receipt on a bound pair remaining partial rather than fabricating a receipt. `completed_at` grants no authority. |
| Duplicate/nonobject/bare nonfinite TEXT rejection and safe error diagnostics | Executed malformed JSON, nesting, numeric-loss, Unicode and invalid identity tests. Scope is validated; unsafe exception context is suppressed. |
| Fresh flat encode mapping, snapshot bytes/tags, stored fingerprint unchanged | Three-state pure and live PG round trips pass. Handwritten evidence tags and preset fingerprints do NOT establish actual `evidence_json` serialization, original-model fingerprinting, or `model_of`/`model_of_json` materialization: those remain UNVERIFIED. |
| Raw/production codec reads on same real migrated DB | Proven above, 204/204, not skipped/fake/SQLite evidence. |
| Run payload is a JSONB object, explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED: tests insert representation rows with fixture identity strings, not governed admission or a Run payload. |
| No SQL mutation/HTTP/queue/claim/assessment/scope-policy behavior added | Codec performs pure mapping; this round changes only this report. Replacement/409 precedence belongs to C/F2 and is not claimed. |
| Reachable production behavior and unchanged full required integration CI | NOT proven: source search finds no runtime caller, only codec-to-identity and whitelist imports. Provenance fails. Full integration CI not executed. |
| Mutation/pre-fix evidence | No code or test change; no new mutation experiment claimed. |
| Ownership coordination / activation policy | External prerequisites UNVERIFIED. Neither merge nor activation authorized by this handoff. |

## Disposition

**BLOCKED.** The actual required-gate failure cannot be repaired under this lane's authority: an owner-coordinated reachability authorization must first land on the trusted base, or a separately authorized consumer integration must supply genuine runtime reachability. Do not add candidate grants or cosmetic imports. Supply an assigned-head failing test traceback before attempting the unnamed test repair. Repeating the same dispatch or amending Vulture will not resolve this blocker.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Commit this evidence locally as a handoff only, not integration approval.

# Issue #1893 repair — 30b07e1b

## Scope and disposition

- Assigned writer worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
- Frozen item: #1893 only. Starting source SHA: `770aeeb7ebb90524c32e75516b228555ee65089a`.
- Frozen integration base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Supplied evidence directory: `/home/dev/maistro/jobs/30b07e1b4c334d698cbe5f50243620b8`.
- Initially clean tree; no incoming work to salvage. Investigated existing admission codec, identity constructors, adjacent tests and the named CI gates. **Only this report changes.** No test additions/deletions or inventory delta; no inventory note is necessary.
- **BLOCKED**: reproduced unauthorized reachability debt, not a Vulture or focused-test failure. No speculative source repair, ledger/grant edit, gate weakening, production activation or GitHub mutation.

Read repository instructions, the full captured issue body, captured linked PR bodies/check results, supplied driver logs and previous result, relevant implementation/tests, quality policy and accepted ADR-081426-1f7c / ADR-082526-7f02. The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model and immutable admission provenance remain unchanged. No alternative execution, event or authorization authority is introduced.

Ambiguity resolved for this round: the prompt says `test: failure` but supplies no failing node or traceback at the assigned head. The captured failing `test` check belongs to #1855 SHA `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; #1945's captured failing check is `exact-debt-ledger` at `fcc8b437f209a35aa68a61d6f0a5387414938355`. Neither establishes a test defect at this source SHA. Assumption: reproduce the focused contracts and required debt gate, not change code based on another head's check label. Current full-CI failure remains UNVERIFIED.

`git merge-base HEAD 3c761d14db944a727fa0744444bc67cfe36d49f7` returned the assigned base. There is no develop-sync conflict to resolve. No remote refs were fetched or changed.

## Independently executed gates

All validation used `uv run`; each validation subprocess had a 1200-second timeout. Logs named below are in the supplied evidence directory. Driver checks were also inspected (201 passed / 3 skipped, ruff/format/inventory passing) but were not treated as fresh PostgreSQL evidence.

| Command | Outcome / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings, zero unclassified; `worker-vulture.log`. No ledger amendment warranted. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | **FAIL, exit 1**: two unauthorized unreachable modules and their dispositions; `worker-provenance.log`. |
| `uv run ruff check .` | PASS; `worker-ruff.log`. |
| `uv run ruff format --check .` | PASS: 3277 files; `worker-format.log`. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files; `worker-mypy.log`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 collected nodes, no duplicate evidence; `worker-inventory.log`. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-surface.log`. |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger: 1396 modules, 171 unreachable; `worker-reachability.log`. |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger: 50 groups, 171 modules; `worker-dispositions.log`. |
| `uv run python scripts/check-promotion-surface.py` | PASS: 74 tolerated modules; `worker-promotion.log`. |

The trusted-base failure names `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`: base 169 unreachable/dispositioned modules -> candidate 171. Evidence locations are `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. The required workflow runs this provenance check at `.github/workflows/vulture-ratchet.yml:77`. Candidate-ledger consistency does **not** authorize expansion. The repair exception permits reviewed Vulture amendments only, not reachability authorizations.

Source search (`rg -n 'admission_codec|admission_identity' packages/*/src`) finds only the codec's identity import and a Vulture-whitelist import, not a runtime consumer. The codec explicitly documents its inactive status at `packages/maistro-core/src/maistro/tasks/admission_codec.py:51-54`. Adding a fake caller/export is not a repair. An independently authorized trusted-base prerequisite or separately authorized consumer integration is required; this lane may manufacture neither.

## Fresh migrated PostgreSQL evidence

Inspected the existing lane-local `auto-1893-pg` container (`pgvector/pgvector:pg18`, localhost port 15498). Verified the new database name was absent before creating **only** disposable database `maistro_1893_30b07e1b`. Existing databases were not reused or modified. Used the container's existing credential through process environment, never logged or committed it.

Executed `uv run alembic upgrade head`: PASS, real chain from empty -> 001 -> ... -> 055 -> ... -> 062 (`worker-migrations.log`). No SQLite/schema recreation or destructive downgrade. PostgreSQL reports version 18.6.

With nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` pointing to that same database, `MAISTRO_REQUIRE_PG_LEGS=1`, `REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/30b07e1b4c334d698cbe5f50243620b8/worker-pg-tests.xml
```

**204 collected, 204 passed, zero errors/failures/skips** (1.52s), at the starting source SHA. `worker-pg-tests.log` and XML retain results, node identities and session properties. The production-codec pool was non-None; raw/production pools read the same database/server (`172.17.0.9/32:5432`) through distinct sessions:

| State | Production PID | Raw PID | Persisted admission rows |
| --- | ---: | ---: | ---: |
| unbound | 18817 | 18818 | 1 |
| bound | 18819 | 18820 | 1 |
| acknowledged | 18821 | 18822 | 1 |

The existing tests inject escaped lone-surrogate TEXT into each snapshot column, require typed safe failures through both pools and preserve header evidence. They independently assert migration-055 binding shape instead of merely checking encode/decode agreement. Independent final SQL counts: task_idempotency=0, canonical_runs=0, canonical_projects=0; Alembic revision=062 (`worker-pg-counts.log`). The disposable database is retained for handoff. No pre-fix or mutation execution is claimed in this unchanged-source round.

## Acceptance audit

| Criterion | Evidence or explicit limit |
| --- | --- |
| Frozen/slotted header; exact shared interfaces, six codes, named columns and header/row scalar agreement | Source inspection plus passing header, scalar, missing-column and mismatch tests. |
| Strict storage UUID `.hex`, signed timestamps, #1851 constructors, fresh flat encode mapping | Passing owner/generation, timestamp, constructor and encode tests. |
| V2 request/receipt/provenance snapshot preservation, optional binding and acknowledgment | Three-state tests pass in memory and on the real migrated schema, including independent task_id=receipt_id/run_id shape checks. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run without guessing identity | Passing legacy tests, including bound pair with explicit receipt and partial pair without receipt. Reconciliation: #1851's binding constructor needs receipt evidence; the no-invention rule takes precedence over reading 'both task_id/run_id is bound' as permission to fabricate that missing receipt. |
| Minimal header survives malformed snapshots/partial bindings; no expiry or fingerprint assessment in codec | Both named header-separation tests pass; source accepts no clock or incoming fingerprint. Inclusive-expiry replacement and 409 precedence belong to the future consumer, not this leaf. |
| Unknown formats/scalar corruption fail closed; strict TEXT JSON and safe exceptions | Passing format, duplicate/nonobject/nonfinite, recursion, numeric fidelity, Unicode, predecoded-value and error-hygiene tests. |
| Arbitrary permitted tagged program_context evidence and unchanged stored fingerprint | Tagged nan/inf/-inf tests pass; decoder preserves tags and stored fingerprint without double decoding or recomputation. |
| Real evidence-json serialization, model_of/model_of_json materialization and original-model fingerprint computation | **UNVERIFIED** by these tests: tags/fingerprints are manually constructed; no real TaskResponse/Run materialization. |
| Raw and production JSON codec pools read identical TEXT snapshots on the same migrated schema | Executed three-state PostgreSQL tests above; distinct sessions, identical stored text, no skips. |
| Run payload INSERT is a JSONB object, not a doubly encoded string | **UNVERIFIED**: these tests create no canonical Run. |
| Real explicit authorized principals, Workspace/Project and valid Graph kinds | **UNVERIFIED**: direct codec/storage fixtures use placeholder identities; they do not prove authorized admission. |
| No SQL mutation, HTTP/queue response, live assessor/scope utility, clock/claim decision or policy changes in codec | Complete codec inspected; it only reads/returns mappings. Only this report changes in this round. |
| Focused tests, ruff, format, applicable mypy and inventory | Fresh commands pass as recorded above; no new inventory delta. |
| Unchanged full required CI, runtime reachability, independent mergeability | **BLOCKED / UNVERIFIED**: required trusted-base provenance fails; no production consumer; full CI not executed. Passing local contract tests cannot establish product-path acceptance. |
| Coordination/activation/parent closeout | Assigned worktree/base honored; activation remains blocked, no closure or integration approval claimed. |

## Handoff

Changed file: `docs/testing/issue-1893-repair-30b07e1b.md` only. Required next input: trusted-base prerequisite/authorized integration resolution and a current failing test command/node/traceback if a test repair is still requested. Repeating this unchanged blocked lane cannot supply either.

Progress: checked 1 issue, done 0 source repairs, skipped 0, errors 1 unresolved required gate. Final local commit records this handoff only. No push or GitHub mutation.

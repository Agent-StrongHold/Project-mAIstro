# Issue #1893 repair checkpoint — 96e109b6

## Scope and authority

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Clean starting source: `c2d266583e7b24b199db3545350fca6b2105e8e6`.
- Frozen integration base: `3c761d14db944a727fa0744444bc67cfe36d49f7`;
  both local `origin/develop` and `git merge-base HEAD <base>` resolve to it.
- One item: #1893 codec and reported CI failures. No sync conflict exists.
- Read repository instructions, supplied dispatch issue/check evidence, codec,
  identity constructors, adjacent tests, PostgreSQL fixture, migration setup,
  and relevant CI steps. Accepted ADR-081226-a66b, ADR-082526-7f02 and
  ADR-083126-5e62 preserve canonical Goal -> Graph -> Run -> NodeRun -> Attempt,
  immutable admission provenance and trusted-base authorization. A staged DTO
  leaf does not authorize runtime activation or a candidate-written grant.
- Only this report changes. No source/test/ledger/grant/gate edits. No tests
  added, so no inventory delta. Existing work is preserved.

## Independently executed checks

Commands ran at the source above with 1800-second validation timeouts.
Artifacts are in `/home/dev/maistro/jobs/96e109b6b6ad408c8877164157221b21/`.
Driver `check-0.log` through `check-4.log` were inspected, not treated as live
PostgreSQL proof (their focused run was 201 passed, 3 skipped).

| Command | Result / artifact |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities / 1323 findings; `worker-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1; `worker-provenance.log` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3277 files; `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence; `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-surface.log` |

The exact-debt-ledger workflow runs the failed provenance gate at
`.github/workflows/vulture-ratchet.yml:77`. It rejects two new unreachable
modules and two new dispositions: `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` (169 trusted versus 171 candidate). Candidate
entries are at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The Vulture-only repair
exception does not authorize changes to these policies. Vulture itself needs
no amendment. Do not remove ledger entries to conceal actual unreachable code.

## Fresh PostgreSQL evidence

After confirming the database name absent, created the dedicated disposable
`maistro_1893_96e109b6` on local PostgreSQL **18.6**. Ran:

```text
createdb maistro_1893_96e109b6
DATABASE_URL=postgresql:///maistro_1893_96e109b6 uv run alembic upgrade head
```

The real chain ran from empty through **062**, including admission migration
055 (`worker-migration.log`). No SQLite/fake schema or prior migration claim
was used. Downgrade testing was not performed.

With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
`postgresql:///maistro_1893_96e109b6`, and `MAISTRO_REQUIRE_PG_LEGS=1`, ran:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml
```

**204 passed, zero skipped**, 1.37 seconds; see `worker-focused.log` and XML.
The three live cases require non-None `pg_pool`, persist one scoped admission
row each, and compare raw versus production `_register_json_codecs` readers.
Session identities recorded by the tests:

| State | Production PID | Raw PID | Persisted scoped rows |
| --- | --- | --- | --- |
| unbound | 3714993 | 3714994 | 1 |
| bound | 3714995 | 3714996 | 1 |
| acknowledged | 3714997 | 3714999 | 1 |

All sessions report database `maistro_1893_96e109b6`, Unix socket (address/port
NULL). Each case also injects escaped lone-surrogate TEXT into each of the
three snapshot columns; both pools preserve the bytes and decoding fails with
safe typed errors while the header fingerprint survives. The test restores
those columns and deletes its row. Final direct `psql` queries confirm revision
**062**, **0 admission rows / 0 distinct generations / 0 distinct bound Runs**
(`worker-db-counts.log`). The disposable database remains available.

A process-local mutation replaced `encode_admission_record` with a wrapper
that emits `task_id=None`, then executed the existing bound round-trip node.
It failed at `test_admission_codec.py:134` as expected (`worker-mutation.log`).
The wrapper asserted pytest's TESTS_FAILED exit; no on-disk source changed.
This proves the independent SQL mapping assertion catches the known binding
regression, not merely agreement between an equally wrong encoder and decoder.

## Acceptance audit

These are internal codec/storage proofs, **not** reachable production admission.

| Criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header and exact shared interfaces | Source inspection plus scalar/header, enum/error and immutable DTO focused tests pass. |
| V2 round-trip preserves snapshots and returns fresh flat mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` in all three states and `test_encode_returns_a_fresh_flat_mapping` pass; bound mapping mutation fails independently. |
| Owner token hex only at storage, strict UUID and signed timestamps | Named owner-token test, generation-ID, scalar and identity validation cases pass; sanitized failure messages tested. |
| Legacy bound, unbound and partial distinctions without invented identity | Named legacy distinction test and receipt-only, missing-receipt, unreadable/whitespace evidence cases pass. Both IDs without receipt evidence remain partial because the #1851 binding constructor requires receipt identity. |
| Expired legacy header invents no identity | Named test passes; it preserves scalars without reading a clock or making expiry decisions. |
| Header preserves expiry across invalid snapshots | Named test passes; full decoding fails typed without damaging header evidence. |
| Header preserves fingerprint across partial bindings | Named test passes; no payload comparison/assessment is introduced. |
| Unknown formats fail closed; mismatching supplied header rejected | Named unknown-format and scalar-mismatch cases pass. |
| Tagged nonfinite snapshots preserve fingerprint | Named tagged round-trip test passes; tags remain objects and stored fingerprint is not recalculated. |
| Invalid/duplicate JSON rejected safely | Named test plus nesting, numeric-loss, Unicode and predecoded-value cases pass, including live corrupt TEXT. |
| Raw and production codecs see identical TEXT | All three named PostgreSQL cases pass through the real migrated table; SQL columns selected by name, not `SELECT *`. |
| Field mapping and acknowledgement | Binding round-trip, original receipt identity, acknowledgement constraints and ignored legacy `completed_at` tests pass. |
| No SQL mutation, HTTP/queue/policy/scope change or competing authority in codec | Inspected source is a pure Mapping/DTO codec. Production import search finds only codec -> identity and whitelist -> enum references; no admission caller. SQL mutation occurs only in tests. |

**UNVERIFIED / not claimed:** production `encode_evidence` and
`model_of`/`model_of_json` materialization (fixtures hand-build tags), arbitrary
permitted program-context preservation through that production path,
fingerprinting on original models, Run payload TEXT-to-JSONB object insertion,
authorized explicit principals/Workspace/Project/registered Graph admission,
transaction/crash/dispatch invariants, and unchanged full required integration
CI. Expiry replacement and HTTP 409 ordering belong to C/F2, not this codec.
Implementation coordination and activation policy decisions remain external.

## Handoff

The supplied captured check metadata has no current-head failing test traceback;
its `test` failure concerns another linked head and has no output text. After
inspecting driver logs and captured failed-check metadata, the generic
`test: failure` remains **UNRESOLVED**; focused tests reproduce no failure.
Do not invent an unrelated test repair. `worker-captured-failures.log` records
that attribution limit.

Verdict: **BLOCKED**. The mandatory provenance failure is independently
reproduced. Resolution needs an externally authorized integration base/consumer
decision, not self-authorization or fake imports in this lane. Obtain an
attributable CI traceback for the generic test failure before changing code.

Progress: checked 1; done 0 implementation repairs; skipped 0 items; errors 1
mandatory gate. This evidence report is committed locally only; no push,
GitHub mutation, merge, issue closure or integration approval.

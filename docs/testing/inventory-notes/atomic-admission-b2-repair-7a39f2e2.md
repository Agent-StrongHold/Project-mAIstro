---
inventory-delta:
  packages/maistro-core/tests: +0
---
# #1893 repair validation — 7a39f2e2

## Frozen scope and decision

Only issue #1893, assigned branch/worktree `auto-1893`, clean starting source
`c5a6c9e70e4645ee693acdf0d6d35a0a3709b64d`. Verified dispatch base and local
`origin/develop` both resolve to `3c761d14db944a727fa0744444bc67cfe36d49f7`.
No conflict or uncommitted incoming work existed. No fetch, merge, GitHub
mutation, production activation, or ledger/grant/gate change was performed.
This note is the only changed file; no tests were added or removed.

Read repository instructions, the captured primary issue, codec/DTO code and
adjacent tests, and accepted ADRs 081226-9944, 081226-a66b, 082526-7f02,
082826-b601 and 083126-5e62. Reconciliation: preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt spine and immutable admission
provenance. A pure codec is not an execution/authorization authority, and a
candidate ledger cannot authorize itself against protected-base policy.

**BLOCKED, not an integration approval.** The explicitly permitted Vulture
repair has no measured mismatch. The reproduced failure is instead
trusted-base reachability authorization, which this assignment does not permit
changing. No speculative code repair is justified by the supplied CI evidence.

## Fresh worker executions

All commands below ran against the starting source above. Artifacts reside in
`/home/dev/maistro/jobs/7a39f2e2332440d88d031fdcf215362a/` as `repair-*.log`,
`repair-captured-ci.json`, and `repair-focused-pg.xml` (all 204 exact node IDs).

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1918 passed, 310 skipped, 5 aiosqlite closed-event-loop thread warnings; skips are not PG proof |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed, 1323 reviewed identities / 1323 findings; no ledger amendment warranted |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | **Exit 1:** two unauthorized new unreachable modules and two unauthorized dispositions; remaining subchecks passed |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed, 16466 unique nodes, no duplicates |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed |
| `uv run python scripts/check-reachability.py` | Passed against candidate ledger, not authorization proof |
| `uv run python scripts/check-reachability-dispositions.py` | Passed against candidate ledger, not authorization proof |
| `uv run python scripts/check-promotion-surface.py` | Passed |
| `uv run python scripts/check-doc-links.py` | Passed after adding this note; root ruff lint/format also re-run successfully |

The provenance failure names `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`. Existing candidate rows are at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`. Module import search finds no
production codec consumer. Whitelist/test imports are not runtime reachability.
Resolution needs protected-base owner authorization first, or a separately
reviewed real consumer on the coordinated integration, not this leaf pretending
to wire one or editing the gate.

## Real PostgreSQL proof

Created a new disposable `admission_1893_7a39f2e2` DB in the existing assigned
`auto-1893-pg` PostgreSQL 18.6 container. The first setup probe stopped before
mutation because optional `POSTGRES_USER` was unset; the subsequent connection
validated the image's default `postgres` role. No existing DB was modified.
`uv run alembic upgrade head` applied the real chain from empty to revision 062.

With nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and
`MAISTRO_TEST_DATABASE_URL` targeting that same disposable DB, and
`MAISTRO_REQUIRE_PG_LEGS=1`, executed:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/repair-focused-pg.xml
```

**204 passed, zero skipped.** The three raw/production-pool cases required a
non-None production-codec pool and real committed INSERT/readback. Backend PID
pairs (production/raw) were 39728/39729, 39730/39731, 39732/39733 on
`admission_1893_7a39f2e2`, `172.17.0.9/32:5432`. Each asserted one persisted row.
Unbound, bound and acknowledged encodings satisfied the migrated CHECKs;
escaped-surrogate corruption was rejected in each TEXT snapshot through both
pools. Final SQL counts: 0 admission rows, 0 distinct generations, 0 distinct
bound Run identities. DB retained for inspection. No downgrade test ran.

Regression sensitivity: an in-memory-only wrapper forced encoded `task_id` to
NULL, then `pytest.main` selected `test_v2_round_trip_preserves_all_snapshot_bytes`.
Bound and acknowledged cases failed at test line 134; unbound passed
(2 failed, 1 passed, 128 deselected). The probe harness required pytest's
TESTS_FAILED result. No source file was mutated.

## Acceptance evidence and limits

| Criterion | Executed evidence / boundary |
| --- | --- |
| Frozen/slotted header, exact shared API, six typed codes, signed scalars and strict UUID hex | Source/constructor review; focused header/schema/UUID tests and scoped mypy passed |
| V2 snapshot preservation and fresh flat mapping | Three `test_v2_round_trip_preserves_all_snapshot_bytes` states and `test_encode_returns_a_fresh_flat_mapping` passed; independent binding assertions caught the mutation |
| Owner token hex only at storage; safe errors and validated scope | `test_owner_token_is_hex_at_storage_only`, invalid snapshot/UUID/scope tests passed; exception context suppression asserted |
| Bound, unbound, partial legacy evidence, no guessed identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable and whitespace tests passed |
| Minimal header retains expired-row evidence despite malformed full record | `test_expired_legacy_header_does_not_invent_missing_identity`, expiry-with-bad-snapshot and fingerprint-with-partial-binding tests passed; no clock or assessment is implemented |
| Unknown format/header mismatch fail closed | Unknown-format parametrizations and scalar-mismatch tests passed |
| Tagged nonfinite JSON and stored fingerprint unchanged | Tagged snapshot tests passed; handwritten tags do not prove real-model serialization/materialization |
| Strict TEXT JSON rejects duplicate keys/nonobjects/bare nonfinite | Invalid/duplicate JSON, nesting, lossy-number and UTF-8 corruption tests passed |
| Same migrated schema through raw and production JSON codec pools | All three real-PG cases above passed; no fake/SQLite/skipped durability claim |
| Named columns, acknowledged_at mapping, completed_at never authority | Encoder review, SQL round trips and `test_legacy_completed_at_is_never_read` passed |
| No SQL mutation/HTTP/queue/scope/assessment changes or competing execution authority | Codec remains mapping-only and unreachable; this round changes documentation only |
| Required integration gates and full acceptance | Provenance **failed**; unchanged full integration CI **UNVERIFIED** |

Also **UNVERIFIED** by these staged codec tests: real-model `evidence_json`
encoding and `model_of`/`model_of_json` materialization, fingerprint generation
from the original model, Run `json_of(run)` TEXT-to-JSONB object insertion,
authorized explicit principals/Workspace/Project and registered Graph admission,
C/F2 replacement/409 precedence, production activation and coordination approval.
Synthetic codec identities are not authorization or canonical Run admission proof.

## Failure attribution and handoff

Inspected supplied check-0..4 logs: all pass, but focused check-3 skipped the
three PG cases (superseded for this worker by the zero-skip run above).
Extracted captured check-runs once from the supplied dispatch, without fetching:
`test: failure` is head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (#1855).
Captured #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` has `test: success`
and `exact-debt-ledger: failure`. No assigned-head failing test node or traceback
was supplied. Current-head test-failure attribution remains **UNRESOLVED**.

Checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 unresolved provenance
blocker. Next: owner resolves protected-base authorization and supplies an
assigned-head failing test traceback if another code repair is intended.

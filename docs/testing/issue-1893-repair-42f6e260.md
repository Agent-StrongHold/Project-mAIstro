# Issue #1893 repair checkpoint — 42f6e260

## Frozen scope

- Sole issue: #1893; writer in `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Verified clean starting HEAD: `e534a538ae6675f521c4aa3aca5515c5e98ed085`.
- Assigned develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Evidence snapshot: job `42f6e26091d34957ac8c2d47c4020c11`, supplied dispatch-context.json and check-0.log through check-4.log; supplied prior result `2a6dcd5490784045ac5998291c4c74f4/result.json`.
- Production/test review limited to admission_codec.py, admission_identity.py,
  test_admission_codec.py, test_root_admission_identity.py, their schema/fixture
  dependencies, relevant ADRs and CI gate definitions. No new issues or PRs.
- Planned writable file: this report; codec/test repairs only upon reproduced
  evidence. No reachability ledger/grant changes. Vulture ledger changes only
  if the explicitly required scan reports retained identities needing review.

## Initial findings and assumptions

The issue explicitly stages a pure codec without production activation; accepted
ADRs and the canonical Goal -> Graph -> Run -> NodeRun -> Attempt model remain
authoritative. The generic CI `test: failure` has no detailed failure in the
prompt; inspect supplied evidence before changing code. No develop sync conflict
is present. Earlier verification claims are not evidence for this execution.

## Supplied deterministic evidence inspected

Driver check-0: dependency sync succeeded; check-1: Ruff passed; check-2:
3301 files formatted; check-3: 346 passed, 3 skipped; check-4: core inventory
16567 unique identities, no duplicate evidence. These logs do not reproduce
the generic `test: failure`, and skipped PostgreSQL tests are not durability
proof. Prior result is BLOCKED; its measurements are historical, not reruns.

Codec source explicitly states it is not yet production-consumed. The issue
prohibits activating the later C consumer in this leaf, so adding artificial
reachability is not a legitimate repair.

## Fresh gate result

Executed exact Vulture scan: **PASS**, 1322 reviewed findings, zero unclassified;
no ledger amendment is warranted. Verified supplied base resolves, then ran
`RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`:
**FAIL (exit 1)**. Both `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` are new unreachable modules and new dispositions
without already-landed authorization (169 -> 171). This is actual current
evidence, not an inferred scanner defect. The vulture-only repair exception
cannot authorize reachability policy changes.

Read accepted ADR-081226-69ee (canonical execution ownership),
ADR-082526-7f02 (immutable admission provenance), ADR-083026-aba1 (state absent
callers), and ADR-083126-5e62 (trusted-base governance). No conflicting issue
text licenses new execution/authorization paths or candidate self-approval.
## Independently executed focused validation

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`: **346 passed, 3 skipped** (PG not configured).
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**, two files.
- Production-source search for `admission_codec|admission_identity`: only the
  codec's identity import and the Vulture whitelist import; no live consumer.
- The attempted path `alembic/versions/055_atomic_root_admission.py` was not
  found; skipped. Resolve the actual schema filename before inspection.

## Live PostgreSQL evidence

Created a fresh disposable database `maistro_1893_42f6e260` on the existing
Docker PostgreSQL service, refusing reuse. Credentials obtained privately from
container configuration, never persisted in this report. `DATABASE_URL`,
`MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL` all targeted that DB;
`MAISTRO_REQUIRE_PG_LEGS=1`. No shared database was migrated or truncated.

- `uv run alembic upgrade head`: **PASS**, real chain from empty DB through
  migration **063**, including `055_task_admission_generations.py`.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q --junitxml=/tmp/1893-42f6e260-pg.xml -o junit_family=legacy`:
  **204 passed, zero skipped**, PostgreSQL **18.6**.
- Same database/server verified by the tests: `maistro_1893_42f6e260`,
  `172.20.0.2/32:5432`; production/raw PID pairs **300941/300942** (unbound),
  **300943/300944** (bound), **300945/300946** (acknowledged). Each pair read
  exactly one committed row with matching TEXT snapshots and encoded scalars.
- Independent final SQL counts: `task_idempotency=0`, `canonical_runs=0`.
  Disposable DB retained; no downgrade or destructive migration tests run.

Existing tests use synthetic envelope identities. These results prove real
row transport and schema binding constraints, not authorized admission or Run
JSONB persistence.

## Additional validation and regression sensitivity

- `uv run pytest packages/maistro-core/tests/extensions -x -q`: **1092 passed**.
  No failing extension regression reproduced; no speculative assertion edits.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  **PASS**, 16567 collected unique identities, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: **PASS**.
- `git diff --check`: **PASS**.
- In-memory mutation only: wrap `encode_admission_record` to force
  `task_id=None`, then execute `pytest.main(['packages/maistro-core/tests/tasks/test_admission_codec.py', '-q', '-k', 'test_v2_round_trip_preserves_all_snapshot_bytes'])`.
  **Expected 2 failures, 1 pass, 128 deselected**: bound/acknowledged cases fail
  at `test_admission_codec.py:134`. This independently demonstrates that the
  existing test detects the historical missing binding identity rather than
  merely comparing a mutually broken encoder and decoder. No source mutated.

## Acceptance audit

| Criterion | Evidence and boundary |
| --- | --- |
| Frozen/slotted `AdmissionRowHeader`, six failure codes, exact public interfaces | Source reviewed; focused codec and identity tests passed. No clock or request fingerprint arguments exist. |
| Strict storage UUID hex, signed timestamps, header mismatch rejection and unknown formats fail closed | Existing rejection tests passed at the exact starting HEAD. |
| Error scope is only a validated hash; no snapshot/owner text in diagnostics; suppressed parser chains | Existing invalid JSON, Unicode, nesting and UUID tests passed. |
| Legacy bound/unbound/partial/receipt-only distinctions without guessing identity | Existing tests passed. A bound pair without explicit receipt evidence is partial because `AdmissionBinding` requires a receipt; it is not fabricated from another identifier. |
| Header preserves scalar expiry/fingerprint even when full decode fails | Header-separation tests passed. Actual expiry replacement/409 precedence is C/F2 behavior, not implemented or claimed here. |
| Strict object snapshots, duplicate/nonfinite rejection, tag/context preservation and unchanged fingerprint | Existing tests passed including lossy-number and UTF-8 boundary cases. Actual `model_of`/`model_of_json` materialization of TaskResponse/Run remains **UNVERIFIED**; these tests use pre-tagged synthetic snapshots. |
| Fresh flat named SQL mapping, correct `task_id`/`run_id` binding shape | Existing mapping assertions, live migration-055 CHECK-conforming INSERTs and negative mutation prove this. Physical `request` TEXT maps to DTO `request_snapshot`; no renamed schema column assumed. |
| Same migrated DB read through raw asyncpg and production JSON codecs | **204 passed, zero skips** on PG18.6/migration063, distinct backend sessions and identical stored TEXT; one row per scope and zero final residue. |
| Explicit authorized principals, Workspace/Project, valid registered Graph, Run JSONB object | **UNVERIFIED**. Synthetic SQL row fixtures are not admission authorization evidence; no canonical Run was inserted. |
| No SQL mutation/HTTP/queue/assessment changes, production activation, or new execution authority | Codec source is a pure mapping contract; no production/test changes this round. Production search found no runtime consumer, explicitly matching the staged B2 boundary but not runtime readiness. |
| Focused pytest, Ruff, formatting, mypy and truthful inventory | Independently passed above. No tests added/removed this round; inventory delta zero, no new inventory note needed. |
| Vulture exact ledger / reachability-disposition provenance / shipped-surface | Exact Vulture and shipped-surface **PASS**. Trusted-base provenance **FAILS** for two new unreachable modules/dispositions; candidate bookkeeping does not authorize them. |
| Generic CI `test: failure`, full unchanged integration CI and external coordination/policy release | Failure not reproduced in focused/extension suites; detailed failing CI node not supplied. Full integration CI and external release **UNVERIFIED**. This report does not claim closure, independent mergeability, or rollout approval. |

## Handoff

Only `docs/testing/issue-1893-repair-42f6e260.md` changed. No justified codec
repair emerged, and the exact Vulture scan needs no amendment. The remaining
actual blocker is `quality/reachability-baseline.json:131,147` plus
`quality/reachability-dispositions.json:612-613`, which predate this round.
The mandatory trusted-base check rejects them against the supplied base.
Resolving that requires separately reviewed protected-base authorization or
separately coordinated genuine runtime integration, outside this writer's
permission; fake imports, candidate grants, or gate edits are not repairs.

No sync conflict existed, no merge was attempted, and no remote operations or
GitHub mutations were performed. No earlier work was discarded. Progress:
**checked 1, done 0, skipped 0, errors 1** (provenance blocker). Next: campaign
owner resolves the governance/coordination blocker; obtain the actual failing
CI test log before any further test repair. Verdict: **BLOCKED**. Commit this
report as the local handoff; do not treat it as integration approval.

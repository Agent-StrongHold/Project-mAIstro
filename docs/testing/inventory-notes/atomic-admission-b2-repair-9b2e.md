---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — 9b2e

Starting HEAD `363c06ddb6acc2a2545a43a9cf2228a283abe93f`, assigned branch
`auto-1893`, supplied base `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b`.
Clean starting worktree verified. Scope frozen to codec, codec tests, this note,
and the explicitly permitted Vulture ledger if the actual scan warrants it.
No inherited changes discarded; no develop merge necessary (no conflicts).

Inspected supplied dispatch issue/PR evidence, prior result, driver logs,
codec/tests, and accepted ADR-081226-a66b and ADR-083126-5e62. Reconciliation:
this is staged DTO validation, not production activation or independent
integration approval. Physical `request` TEXT follows migration 055; task
binding follows its paired-column CHECK, not a fabricated new identity.
The canonical execution/authorization model remains unchanged.

Fresh results so far (logs in `.pytest_cache/repair-9b2e/`):

- Exact instructed Vulture command passes: 1326 findings / 1326 reviewed
  identities. No ledger amendment is justified.
- `RATCHET_BASE_REV=d99e598e1084a183d1280fbe9a2c4de8b50b7f2b uv run python
  scripts/check-ratchet-provenance.py` fails. `provenance.log:21-30` rejects
  new reachability dispositions and unreachable modules for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` at
  trusted merge base `e46ad6708fda`. Candidate banking is not authorization.
- Prior binding defect is already repaired in source: `task_id` uses
  `binding.receipt_id`; unit tests independently assert the SQL shape.
- Driver sync, lint, format and inventory passed, but driver focused tests
  were 201 passed / 3 skipped. Those skips do not prove database behavior.

No evidence-backed in-scope code repair identified. Vulture permission does
not authorize reachability grants or dummy production consumers.

## Executed validation

All source validation ran at the starting SHA above; this note is the only
changed file. Logs are retained under `.pytest_cache/repair-9b2e/`.

- `createdb maistro_1893_9b2e` then
  `DATABASE_URL=postgresql:///maistro_1893_9b2e uv run alembic upgrade head`:
  passed the real chain through 061, including 055, on a newly created
  dedicated disposable PostgreSQL database. No stamping or SQLite substitute.
- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_9b2e`, plus `MAISTRO_REQUIRE_PG_LEGS=1`, then
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-9b2e/focused.xml`:
  **204 passed, zero skips**. Same paths with `--collect-only -q`: 204 nodes
  recorded in `nodes.log`.
- Raw/production PostgreSQL session PID pairs, respectively:
  **3064606/3064605**, **3064608/3064607**, **3064610/3064609** for unbound,
  bound and acknowledged. Each test requires non-null `pg_pool`, confirms
  same database/server identity, and asserts exactly **one scoped row**.
  TEXT snapshots, decoded DTOs and re-encoded mappings agree through both
  pools. Escaped-surrogate TEXT injected into each snapshot column fails
  safely through both pools. Final SQL: revision **061**, **0 rows**,
  **0 distinct generations**, **0 bound Runs** after test cleanup. DB retained.
- Process-local mutation replaced encoder `task_id` output with `None`, then
  ran `pytest.main` on the codec file with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected exit 1,
  **2 failed, 1 passed, 128 deselected**. Both bound states fail the independent
  assertion at `test_admission_codec.py:134`. No on-disk source mutation.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3195 files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 15932 unique identities.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed as recorded above.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: passed.
  These candidate checks do not override the trusted-base provenance failure.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  **1 failed** at line 287. Rich wraps `not\na hex Ed25519 private key`,
  breaking the contiguous substring assertion. The failure is outside this
  codec lane; correlation with hosted `test: failure` is **UNVERIFIED**
  because no hosted traceback was supplied. No unrelated repair attempted.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src` finds only
  codec-to-types and whitelist references, no production consumer.

## Acceptance matrix

These are internal contract proofs, not reachable production admission proofs.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header and shared DTO interfaces | Source inspection and the 204-test codec/identity run; named scalar mapping, fresh flat encoding and constructor validation pass. |
| Exact v2 snapshot round trip | Unbound/bound/acknowledged unit and migrated two-pool tests pass; independent mutation catches both bound regressions. |
| Owner token hex only at storage | Strict UUID forms, nil rejection and repr-hygiene tests pass; DTO retains UUID. |
| Legacy bound/unbound/partial distinction | Complete explicit receipt/binding, neither-set, partial pairs, receipt-only, missing receipt and unreadable evidence tests pass; no missing identity invented. |
| Expired legacy header does not invent identity | Named test passes, preserving scalars without any clock or admission decision. |
| Header expiry survives corrupt snapshot | Named malformed/duplicate JSON tests pass while header remains intact. |
| Header fingerprint survives partial binding | Named test passes with original fingerprint unchanged. |
| Unknown formats fail closed | Unknown/null/bool/float and header mismatch tests pass, no legacy reinterpretation. |
| Tagged nonfinite snapshots | Synthetic nan/inf/-inf tag preservation tests pass without fingerprint recomputation. Real model `encode_evidence` -> `model_of`/`model_of_json` materialization and arbitrary permitted program_context remain **UNVERIFIED**. |
| Strict JSON and safe parsing failures | Duplicate/nonobject/bare nonfinite, overflow/lossy numbers, nested data, Unicode, and suppressed error-chain tests pass. |
| Raw vs production JSON-codec pools | Real migrated PostgreSQL evidence above; three tests ran, none skipped. |
| Stage boundaries | No source, scheduler, SQL writer, HTTP response, queue, clock, assessment, fingerprint algorithm, authorization or policy changes. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. |
| Production reachability / unchanged required CI | **Not established**: no consumer; trusted-base provenance fails. Full required hosted CI **UNVERIFIED**. |

Also **UNVERIFIED**: explicit authorized principals/Workspace/Project and
registered Graph admission, Run `json_of(run)` TEXT-to-JSONB object insertion,
live inclusive expiry/409 ordering, transaction/crash/dispatch invariants,
and destructive downgrade/adoption. DTO inserts with synthetic IDs do not
prove those contracts. No migration-chain downgrade test was run.

## Final handoff — BLOCKED

Only this inventory/evidence note changed; no new tests, source fixes, ledger
amendments, grants, gate weakening or GitHub mutations. The prior code repair
is valid under focused and real DB tests, but this branch is not merge-ready.
Resolve the two inactive modules via coordinated genuine consumer wiring or
separately landed trusted-base authorization; neither is authorized in this
repair lane. Route the reproduced CLI assertion failure to its owner and
obtain the actual hosted traceback before attributing the generic CI failure.
Do not redispatch unchanged codec work expecting Vulture banking to resolve
reachability policy.

Progress: checked 1 issue; done 1 validation/handoff; skipped 0 issues;
errors 2 unresolved checks (provenance, unrelated CLI assertion).
Next: coordinated reachability/authorization resolution and test-owner repair.

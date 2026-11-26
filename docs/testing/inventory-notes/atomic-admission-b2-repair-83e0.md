---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair — 83e0

## Scope and checkpoint

Writer assignment, clean starting HEAD `1be66cb24a8f9e789e8cd6e54ac5f1794c969310`,
branch `auto-1893`, supplied verified base
`b02817d5482d252bf67b15d91eb6d4d397e3679c`.
Frozen scope: codec, adjacent codec tests, permitted Vulture baseline repair
only if the exact scan finds discrepancies, and this note. Surrounding
identity types, migration 055, ADRs, workflows and dispatch evidence are
read-only. Existing branch changes are preserved. Historical coordination
requirements are reconciled as staged local validation only, not permission
to activate a consumer or integrate the branch.

Driver logs inspected: sync/lint/format/inventory passed; focused pytest
201 passed / 3 skipped. Those skips establish no PostgreSQL behavior.
Prior binding finding is already fixed in the starting source: encoder
uses `binding.receipt_id` for `task_id`, matching migration 055's paired
binding CHECK. No speculative rewrite is justified.

Fresh exact Vulture scan passed (1326 findings / 1326 reviewed identities).
No ledger amendment is warranted. Fresh trusted-base provenance check failed:
`RATCHET_BASE_REV=b02817d5482d252bf67b15d91eb6d4d397e3679c uv run python
scripts/check-ratchet-provenance.py` reports NEW unauthorized reachability
and dispositions for `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` against merge base `e46ad6708fda`.
Logs: `.pytest_cache/repair-83e0/{vulture,provenance}.log` (provenance lines
21–30). The explicit repair exception covers Vulture, not authorization
ledgers or a fake consumer. This blocker cannot be fixed within lane scope.

One guessed quality-ADR filename was not found and skipped; the actual
`ADR-083126-5e62-generated-quality-evidence-is-not-the-judge.md` was resolved
by filename lookup. No unresolved git refs were executed.

## Validation results

All commands below were freshly executed against the starting source SHA.
Only this note changed; no source, test, baseline or grant edits were needed
or authorized by the observed failures. Logs are retained under ignored
`.pytest_cache/repair-83e0/`.

- `createdb maistro_1893_83e0` and
  `DATABASE_URL=postgresql:///maistro_1893_83e0 uv run alembic upgrade head`:
  passed, real migration chain through 061 including 055, on a new dedicated
  disposable local PostgreSQL DB. No schema stamping or SQLite substitute.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both set to
  `postgresql:///maistro_1893_83e0`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-83e0/focused.xml`:
  **204 passed, zero skips**. Same paths with `--collect-only -q`: 204 nodes
  recorded in `nodes.log`.
- Real raw/production-pool tests require non-null `pg_pool`. Production/raw
  session PID pairs: **2140965/2140966** (unbound), **2140967/2140968** (bound),
  **2140970/2140971** (acknowledged), all on the same socket and DB above.
  Each asserts **one persisted scoped admission row**, matching TEXT values,
  DTOs and re-encoded mappings. Injected escaped-surrogate TEXT is rejected
  in all three snapshot columns through both pools. JUnit records sessions
  and row counts. Final SQL: migration 061; **0 rows, 0 distinct generations,
  0 bound Runs** in `task_idempotency` after test cleanup. DB retained.
- Process-local mutation replaced encoder output `task_id` with `None`, then
  invoked `pytest.main` on codec tests with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected exit 1,
  **2 failed, 1 passed, 128 deselected**. Both bound states fail the independent
  storage assertion at line 134. No on-disk mutation or discarded work.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3195 files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 15932 unique test identities; zero
  additions/removals in this round.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1326 reviewed
  identities / 1326 findings. No unbanked identity justifies ledger edits.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: passed.
  Candidate checks do not supersede the failed trusted-base provenance gate.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  **failed** at line 287: Rich wraps `not\na hex Ed25519 private key`, breaking
  the contiguous substring assertion. This independently reproduces the
  prior unrelated failure. Its correspondence to the generic hosted
  `test: failure` remains UNVERIFIED; no hosted traceback was supplied.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src` found only
  the codec-to-types import and Vulture whitelist import, not a production
  consumer. Exports/tests/whitelists are not execution reachability.

## Acceptance matrix

Each codec criterion below has direct unit coverage in the 204-node run;
passing internal tests is not proof of reachable production admission.

1. **Immutable interfaces / exact named fields:** header is frozen/slotted;
   header and full-record decode are separate; constructor-backed DTOs and
   six typed error codes inspected. Signed scalars, mismatch rejection and
   fresh flat mappings pass tests. Physical `request` TEXT maps to the DTO's
   `request_snapshot`, following the shipped migration rather than a new
   column or guessed identity.
2. **V2 byte-preserving round trip:** unbound/bound/acknowledged unit and
   migrated two-pool tests pass. The mutation detects the old binding defect.
3. **Storage-only owner UUID hex:** strict storage UUID, nil/invalid forms and
   repr-hygiene tests pass; DTO owner remains UUID.
4. **Legacy bound/unbound/partial:** tests distinguish explicit complete
   receipt/binding evidence from absent, one-sided, receipt-only, missing
   receipt and unreadable evidence; never invent a missing identity.
5. **Expired legacy header:** test preserves scalar evidence without a clock
   or creating identities. No expiry/assessment/claim policy is implemented.
6. **Header expiry despite malformed snapshot:** duplicate/invalid JSON
   full-decode failures leave the header intact; tests pass.
7. **Header fingerprint despite partial binding:** test passes; stored
   fingerprint is not recomputed from canonicalized or tagged snapshots.
8. **Unsupported format:** unknown, null, bool, float and mismatched header
   tests fail closed without legacy reinterpretation.
9. **Tagged nonfinite snapshot preservation:** nan/inf/-inf tag tests pass.
   Actual model-level `encode_evidence` -> `model_of`/`model_of_json` round
   trips and arbitrary permitted program_context materialization remain
   **UNVERIFIED** here; fixtures are synthetic JSON, not production models.
10. **Strict JSON / safe errors:** duplicate keys, nonobjects, bare nonfinite,
    overflowing/lossy numbers, deep nesting, invalid Unicode and suppression
    of unsafe parsing chains pass tests. No raw owner/snapshot is emitted.
11. **Raw vs production pool codecs:** real DB evidence above proves TEXT
    mapping equality for all three states; not skipped, fake or SQLite proof.
12. **Stage constraints:** no scheduler, SQL mutation, HTTP mapping, admission
    decision, authorization path or policy activation was added. Accepted
    ADR-081226-a66b keeps Run lifecycle authority; ADR-083126-5e62 prevents
    candidate evidence from granting its own quality authorization. Canonical
    Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged.

**UNVERIFIED / not established by this leaf:** production reachability;
explicit authorized principals and Workspace/Project/registered Graph
admission; Run `json_of(run)` TEXT-to-JSONB object insertion; live inclusive
expiry/409 ordering; transaction/crash/dispatch invariants; destructive
migration downgrade/adoption; all unchanged required hosted CI. The real
upgrade and DTO storage tests do not establish those stronger claims.

## Handoff — BLOCKED

Only this inventory/handoff note is changed. There is no evidence-backed
in-scope source repair remaining. The exact-debt job's provenance step fails
before Vulture, which already passes. Resolve the two inactive modules via
coordinated genuine consumer wiring or separately landed trusted-base
permission; this lane cannot create that authority. Route the reproduced
CLI assertion failure to its owner and obtain the actual hosted traceback
before attributing the generic test failure. No merge, push, GitHub mutation,
gate weakening, cosmetic source change or destructive git operation occurred.

Progress: checked 1 issue; done 1 validation/handoff; skipped 0 issues;
errors 2 unresolved checks (provenance, unrelated CLI assertion).
Next: coordinated authorization/consumer resolution and test-owner repair;
do not redispatch unchanged codec work as if another Vulture amendment could
resolve the provenance failure.

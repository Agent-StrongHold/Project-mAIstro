---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint (d26d)

Frozen scope: issue #1893 only, assigned worktree `auto-1893`, starting HEAD
`74161936545b3052d3df2873683013da1fca0500`, supplied base
`e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. No remote mutations or ref updates.
Candidate files: admission codec, its adjacent tests, this inventory note, and
`quality/vulture-baseline.json` only if the explicitly authorized exact-debt
repair requires it. Other authority/ledger changes remain out of scope.

Initial evidence: worktree clean and HEAD matches assignment. Driver logs show
ruff and inventory passing, focused tests 201 passed / 3 skipped. Prior bound
encoding finding is already repaired at the assigned HEAD (encoder writes
binding.receipt_id to task_id and tests independently assert it). Prior report
is evidence, not validation for this round.

Ambiguity: dispatch names a generic CI `test` failure without its traceback.
Proceed by reproducing focused tests, real PostgreSQL contrast, and named gates;
do not guess a production repair or activate the staged codec to evade debt.
The supplied prior artifact reports unresolved reachability/disposition grants;
only vulture ledger changes are authorized in this round.

Checkpoint: fresh exact vulture scan passes (1326 findings / 1326 reviewed
identities). Fresh provenance gate fails against the supplied base: both
admission_identity and admission_codec add unauthorized reachability and
dispositions (trusted merge base `2a11c1cc006a`). No vulture ledger edit is
justified. Production import search finds no consumer of admission_codec.
Accepted ADR-081226-a66b preserves canonical lifecycle authority; accepted
ADR-083126-5e62 forbids candidate evidence from approving its own debt.
B2 explicitly excludes consumer wiring, so neither fake wiring nor new grants
are a permissible repair. Docker is unavailable; local PostgreSQL is accepting
connections and will be used for an isolated disposable DB.

Checkpoint: disposable DB `maistro_1893_d26de939` migrated through real chain
to 061. Focused codec + identity tests: **204 passed, no skips**, including all
three states with raw and production pools. Bound-encoder mutation: **2 failed,
1 passed** as expected. Full core test run stopped at an unrelated CLI output
wrapping assertion (`test_cli_certification.py:287`): **1 failed, 3661 passed,
79 skipped, 1 xfailed**; isolated rerun reproduces it. No out-of-scope CLI repair.
Initial inventory run rejected this note's empty inline delta syntax; corrected
to the repository's indented suite/zero format. Final rerun follows.

## Final disposition: BLOCKED

Only this note changed. No source, tests, ledgers, grants or integration wiring
changed; existing repairs were preserved. Inventory delta is zero. This is not
integration approval. Local source under validation is the exact starting SHA
above, with only this documentation note added.

### Executed validation

Logs are in `/home/dev/maistro/jobs/d26de939b2124735b622858963e9e429/`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 reviewed
  identities / findings (`worker-vulture.log`). No amendment warranted.
- `RATCHET_BASE_REV=e46ad6708fda20f76b8915679ef701f3ddb6b7e2 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**, unauthorized new modules
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` and
  their dispositions (`worker-provenance.log:21-32`). Other subchecks pass.
  Trusted merge base is `2a11c1cc006a`, not the candidate ledger.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`:
  **passed**, 3185 files; `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `createdb maistro_1893_d26de939` followed by
  `DATABASE_URL=postgresql:///maistro_1893_d26de939 uv run alembic upgrade head`:
  **passed** (`worker-migrate.log`). Dedicated disposable DB, no stamping,
  SQLite substitute or destructive downgrade.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_d26de939`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml`:
  **204 passed, zero skips** (`worker-focused-pg.log`). Non-null production
  codec pool and raw pool backend PID pairs were **1207526/1207527** unbound,
  **1207529/1207530** bound, **1207531/1207533** acknowledged, same database
  via local socket. Each case asserted exactly one persisted scoped row and
  matching encoded/read-back mappings. Corrupt surrogate TEXT was rejected
  from all three snapshot columns through both pools.
- `psql postgresql:///maistro_1893_d26de939 -X` queried revision and final
  admission counts: **061**, **0 rows / 0 generations / 0 bound Run IDs**
  after test cleanup (`worker-db-counts.log`).
- Process-local encoder mutation (no disk edits) forced `task_id=None`:
  `pytest.main([...test_admission_codec.py, '-q', '-k',
  'test_v2_round_trip_preserves_all_snapshot_bytes'])`: **2 failed, 1 passed,
  128 deselected**, expected failure at line 134 for bound and acknowledged
  states (`worker-binding-mutation.log`). This proves sensitivity of the
  existing repair, not a new code change.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests --timeout=30 -x -q`: **1 failed, 3661 passed,
  79 skipped, 1 xfailed** (`worker-core.log`). Failure:
  `extensions/test_cli_certification.py:287` expects the contiguous phrase
  `not a hex Ed25519 private key`, but output wraps between `a` and `hex`.
  `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`
  reproduces **1 failed** (`worker-cli-repro.log`). This unrelated test file
  is outside the frozen repair scope. Remaining core tests were not run after
  the `-x` stop. The supplied generic hosted `test` failure has no traceback,
  so equivalence to this local failure is **UNVERIFIED**.
- Focused two-file `uv run pytest ... --collect-only -q`: **204 nodes**
  (`worker-nodes.log`). `uv run python scripts/check-suite-inventory.py
  --suite packages/maistro-core/tests`: **passed**, 15860 nodes, no duplicate
  evidence (`worker-inventory.log`), after correcting this note's syntax.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`:
  **passed** (`worker-<name>.log`). These candidate-local checks do not
  override the failed trusted-base gate.

### Acceptance evidence and limits

All ten named prospective codec contracts execute in the 204-node suite:

1. V2 byte-preserving canonical snapshot round trips and fresh flat mapping:
   unbound, bound and acknowledged unit and migrated PostgreSQL tests.
2. Storage-only owner token hex: strict UUID/token tests and repr checks.
3. Legacy bound/unbound/partial distinctions: pair, absent pair, receipt-only,
   missing receipt, invalid/whitespace evidence tests; no inferred identifier.
4. Expired legacy scalar evidence without invented identity: header test;
   no clock/expiry decision exists in this leaf.
5. Header expiry survives invalid snapshot: duplicate JSON test.
6. Header fingerprint survives partial binding: stored-fingerprint test.
7. Unknown format cannot become legacy: seven discriminators, mismatched
   headers, and direct-construction validation tests.
8. Tagged nonfinite snapshot evidence/fingerprint unchanged: all three tags
   survive storage without decoding twice or recomputing fingerprint.
9. Invalid/duplicate/nonobject/bare nonfinite JSON: typed failure tests plus
   numeric-loss, excessive nesting, Unicode corruption and chain suppression.
10. Raw/production pools read identical TEXT: non-skipped migrated DB tests
    and independent sessions/counts above, not the fake value-level contrast.

Inspection confirms named columns, frozen/slotted scalar header, signed int64
validation, #1851 constructors, ignored legacy completed_at and no SQL/HTTP/
queue/clock/assessment changes. The physical `request` column is the DTO's
`request_snapshot`, consistent with migration 055. Binding receipt identity
maps to task_id by that migration's explicit contract, not a guessed ID.

**UNVERIFIED:** reachable production admission consumer, real authorized
Workspace/Project/principal/registered Graph behavior, end-to-end model_of /
model_of_json materialization, actual Run JSONB object insertion, live expiry/
409 precedence, activation and full required hosted CI. Fixtures carry explicit
but synthetic identities; the codec stores snapshot TEXT, not authorization.
These staged tests do not establish production admission or execution authority.

Handoff: legitimate coordinated consumer integration or separately landed
trusted-base authorization is needed; vulture banking cannot fix this blocker.
Obtain the hosted failing-test traceback and route the reproduced CLI wrapping
failure to its owner. Do not repeat an unchanged repair or weaken the gates.
Progress: checked **1**, completed **0 repairs** (validation complete), skipped
**0 items**, errors **2 unresolved checks** (provenance and core test).


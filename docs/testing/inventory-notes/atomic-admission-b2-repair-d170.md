---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair — d170

## Frozen scope

Assigned writer on `auto-1893`, initially clean at
`f55104464494238d7deb096237388933fd9db6a9`, supplied base
`273ff4042350b690e9b6bbf95d934a58ec6ac04d` (also local `origin/develop`).
Only issue #1893: codec, adjacent identity types/tests, inventory note, and
explicitly permitted Vulture ledger repair if actual findings require it.
Migration/ADRs/production callers/CI are inspection evidence. No activation,
GitHub mutation, competing execution authority or other ledger/grant edits.
Historical coordination text conflicts with the explicit local assignment;
assume staged validation only, not integration or rollout authority.

## Evidence checkpoint

Driver check-0 through check-4 logs inspected: sync, lint, format and inventory
passed; focused tests were 201 passed / 3 skipped. Skips are not DB evidence.
Prior binding finding is stale at this head: the encoder already supplies
`binding.receipt_id` as `task_id`, and independent assertions test the mapping.
No speculative source repair is warranted by that finding.

Fresh commands, logs in `.pytest_cache/repair-d170/`:

- Exact requested Vulture scan: exit 0. No unbanked identities to amend.
- `RATCHET_BASE_REV=273ff4042350b690e9b6bbf95d934a58ec6ac04d uv run
  python scripts/check-ratchet-provenance.py`: exit 1. Trusted merge base
  `e46ad6708fda`; both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` remain newly unauthorized unreachable modules
  and dispositions (`provenance.log:21-30`). Candidate banking is not authority.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  exit 1. Line 287 expects a contiguous message, but Rich wraps between `not`
  and `a hex Ed25519 private key`. This unrelated failure is outside codec scope;
  correspondence to the generic hosted `test: failure` remains UNVERIFIED.

The initially requested lifecycle ADR filename did not exist; skipped that
path and resolved the actual `ADR-081226-a66b-run-noderun-attempt-lifecycle.md`.
Unresolved trusted-base authorization must be handed off rather than evaded
with imports or a new execution consumer.

## Final validation

Only this note changed. No source/test/ledger changes: the reported bound
mapping defect is already repaired, Vulture has no discrepancy, and the
remaining failures require different ownership/authority. Reviewed repository
instructions, accepted lifecycle ADR-081226-a66b and quality-authority
ADR-083126-5e62, adjacent identity tests/types, migration 055 and CI arguments.
The physical `request` TEXT column maps to DTO `request_snapshot`; assigning
an existing binding's receipt to `task_id` follows migration 055 rather than
inventing identity. Goal -> Graph -> Run -> NodeRun -> Attempt is unchanged.

All results below are freshly executed against the starting source SHA above.
Logs/node IDs/JUnit evidence remain in ignored `.pytest_cache/repair-d170/`.

- `createdb maistro_1893_d170` followed by
  `DATABASE_URL=postgresql:///maistro_1893_d170 uv run alembic upgrade head`:
  **passed**, real chain including 055 through 061. A new dedicated disposable
  local PostgreSQL DB, not a recreated SQLite schema or stamped approximation.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_d170`, plus `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-d170/focused.xml`:
  **204 passed, zero skips**. Same paths with `--collect-only -q`: **204 nodes**.
- Real production/raw pool PID pairs on that same socket/database:
  **1971246/1971250** (unbound), **1971259/1971261** (bound),
  **1971262/1971282** (acknowledged). All three require non-null `pg_pool` and
  assert exactly **one** scoped admission row, equal TEXT bytes and mappings,
  and identical DTOs through both readers. Corrupt surrogate TEXT in each
  snapshot column is rejected through both pools. JUnit records sessions/counts.
- `psql postgresql:///maistro_1893_d170 -X -c 'SELECT version_num FROM
  alembic_version; SELECT count(*) AS rows, count(DISTINCT generation_id) AS
  generations, count(DISTINCT run_id) AS bound_runs FROM task_idempotency;'`:
  **061; 0 rows / 0 generations / 0 bound runs** after cleanup. DB retained.
- Process-local mutation under `uv run python` wrapped the encoder to force
  `row['task_id'] = None`, then called `pytest.main` on the codec path with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected exit 1,
  **2 failed, 1 passed, 128 deselected**. Both bound states fail the independent
  storage assertion at test line 134. No on-disk source mutation.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`:
  **passed**, 3195 files; `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15932 unique collected identities;
  no test additions/removals and this note has zero delta.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 reviewed
  identities / 1326 findings. No justified Vulture ledger amendment.
- `uv run python scripts/check-<name>.py`, for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**.
  These candidate checks do not override the failed trusted-base gate above.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src`: only the
  codec-to-types import and Vulture whitelist import; no live consumer found.
  This corroborates, rather than resolves, the trusted-base finding.

## Acceptance matrix

1. **V2 round trip and fresh flat SQL mapping:** all three bound-state unit and
   real migrated pool tests pass; independent storage assertion detects the
   prior regression. Canonical snapshot text is preserved byte-for-byte.
2. **Owner storage-only hex:** strict UUID forms and repr-hygiene tests pass;
   DTO owner remains a UUID, SQL uses lowercase `.hex`.
3. **Legacy unbound/bound/partial:** explicit receipt plus pair is bound;
   absent identity stays absent; partial, receipt-only, unreadable and missing
   receipt evidence fails typed. No guessed identity.
4. **Expired header without identity invention:** scalar-only header test
   passes; no clock, request fingerprint, claim or assessment API introduced.
5. **Header expiry despite invalid snapshot:** malformed/duplicate JSON tests
   retain unchanged header evidence while full decode fails.
6. **Header fingerprint despite partial binding:** test passes; fingerprint
   stays exact and is never recomputed from normalized/tagged snapshot bytes.
7. **Unknown formats fail closed:** unsupported discriminator/header-mismatch
   tests pass; signed timestamps and canonical constructors inspected.
8. **Tagged nonfinite snapshots:** tag-preservation tests pass for nan/inf/-inf.
   Actual `model_of`/`model_of_json` materialization and arbitrary model-level
   program_context evidence remain **UNVERIFIED**: fixtures are synthetic JSON,
   not a production caller. No direct TaskResponse deserialization added.
9. **Strict JSON and safe errors:** duplicate/nonobject/bare nonfinite,
   excessive nesting, lossy number, Unicode and suppressed exception-chain
   tests pass. Frozen/slotted header and named-column decoding confirmed by
   inspection. Legacy completed_at remains unread.
10. **Raw/production codec equivalence:** three real DB cases above pass,
    using production JSON registration and independent raw sessions against
    the same fully migrated DB. No fake/skip durability claim.

**Not proven by this representation-only leaf:** reachable production admission;
explicit authorized principals/Workspace/Project and valid registered Graph
admission; Run payload `json_of(run)`/TEXT-to-JSONB object insertion; live
expiry/mismatch 409 precedence; transaction/crash/dispatch invariants; policy
activation or full unchanged required hosted CI. These are **UNVERIFIED**.
Migration upgrade passed; destructive chain/downgrade/adoption tests were not
run this round. No full-package or full-tree pytest success is claimed.

## Handoff: BLOCKED

Coordinate the genuine consumer or separately landed trusted-base authorization
for the two inactive modules. This lane cannot add authorization or activate a
consumer merely to satisfy reachability. Route the reproduced CLI wrapping
failure to its owner; obtain the actual hosted traceback before attributing
the generic `test: failure`. Do not redispatch an unchanged codec for the same
blocker without new evidence or authority. No pushes, PR/issue actions or
integration approval were performed.

Progress: checked **1**, done **1 validation/handoff**, skipped **0 items**,
errors **2 unresolved checks** (provenance and unrelated CLI assertion).
Next: coordinated reachability resolution and test-owner repair.

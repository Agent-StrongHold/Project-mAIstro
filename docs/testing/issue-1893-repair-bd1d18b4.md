# Issue #1893 repair checkpoint — bd1d18b4

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `795d24fa609279ae6375f5152faab3fc0ff949ae` (verified; clean).
- Dispatch base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Single item: #1893; supplied dispatch snapshot only, no GitHub mutations.
- Inspect existing admission identity/codec, their two focused test files,
  applicable ADRs and CI gates. Repair source/tests only on reproduced evidence.
- Potential edits: this report; admission source/tests only if a failure is
  reproduced; inventory note if tests change; vulture ledger only for actual
  reviewed scanner findings under the explicit CI-repair exception.
- No reachability ledger/grant or activation-policy changes authorized.

## Initial evidence

Driver `check-0.log` through `check-4.log` inspected in job
`/home/dev/maistro/jobs/bd1d18b4cde64fff8774ec7514221daf`:
locked dev sync, ruff, format and core suite inventory passed; focused tests
reported **201 passed, 3 skipped**. Skips are not database durability evidence.
Prior job result reports a trusted-base provenance blocker and no reproduced
`test` failure; those statements are not treated as fresh validation.

Ambiguity: dispatch supplies only `test: failure`, not a failing node/traceback.
Proceed with focused tests and the named debt gate; do not invent a code repair.
The supplied snapshot's issue coordination/activation restrictions remain in
force; this repair assignment authorizes local evidence work, not rollout.

## Results

Fresh named-gate execution at the starting HEAD:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1323 findings, 1323 reviewed identities, zero unclassified. No Vulture ledger amendment is justified.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`: **exit 1**. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` have new unreachable-module and disposition entries not present/authorized in the trusted base. The disposition count increases from 169 to 171. Other constituent provenance gates passed.
- `origin/develop` resolves to the exact supplied base; no unresolved ref or develop-sync conflict exists locally. No ref was refreshed.

Read accepted ADR-081426-1f7c and ADR-082526-7f02, the codec and DTO sources and adjacent codec tests. Admission evidence must remain immutable and cannot become execution/authorization authority. The explicit inactive-leaf scope forbids inventing a runtime caller to evade this failure. The Vulture-only exception does not permit reachability grants/ledger edits. This blocker requires an integration-owner decision outside this repair's permissions.

Further fresh executions:

| Command | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed, two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` | 201 passed, 3 database skips |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed, 16466 nodes, zero duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed |

Source search across `packages/*/src` finds only the codec importing the DTO and a Vulture whitelist import; no runtime codec caller. Read adjacent DTO tests as well. No source failure is reproduced.

## Live PostgreSQL and adjacent validation

Preflight confirmed PostgreSQL 18.6 and absence of the dedicated database
`maistro_1893_jobbd1d18b4`. Executed:

```sh
createdb -h /var/run/postgresql -U dev maistro_1893_jobbd1d18b4
export DATABASE_URL='postgresql://dev@/maistro_1893_jobbd1d18b4?host=/var/run/postgresql'
export MAISTRO_TEST_PG_DSN="$DATABASE_URL"
export MAISTRO_TEST_DATABASE_URL="$DATABASE_URL"
export MAISTRO_REQUIRE_PG_LEGS=1
uv run alembic upgrade head
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-bd1d18b4-pg.xml
```

The real empty-schema migration chain applied through **062**. Focused pytest:
**204 passed, zero skipped** (204 node IDs in the JUnit artifact). The raw and
production-codec sessions used the same socket/database with distinct PID pairs:

| State | Production PID | Raw PID | Persisted admission rows |
| --- | --- | --- | --- |
| unbound | 1226179 | 1226180 | 1 |
| bound | 1226181 | 1226182 | 1 |
| acknowledged | 1226183 | 1226184 | 1 |

An independent final `psql` query confirmed migration 062 and **zero rows** in
each of `task_idempotency`, `tasks`, `canonical_runs`, `canonical_node_runs` and
`canonical_attempts`. The disposable database is retained; no downgrade test ran.
Tests inject escaped-surrogate TEXT into each of the three snapshot columns and
verify safe typed rejection through both real pools, preserving header evidence.

Without database environment variables, also executed:

```sh
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q
```

Result: **1918 passed, 310 skipped, 6 warnings** (aiosqlite worker threads attempted
callbacks after event-loop closure). No failing test reproduced the supplied CI
status. These skips are explicitly not database acceptance evidence.

## Acceptance boundaries

All ten prospective named codec tests ran in the live 204-node run:

- Exact v2 snapshot/mapping round trips; fresh flat named-column mappings;
  unbound, bound and acknowledged state; migration-055 binding shape: passed.
- Frozen DTOs, strict storage-only UUID hex and signed timestamp validation,
  mismatched scalar headers, error-code/scope validation and safe suppressed
  parser chains: passed at the codec/DTO boundary.
- Legacy bound/unbound/partial and receipt-only evidence remain distinct;
  no invented generation/owner/receipt/Run identity: passed at that boundary.
- Expiry and fingerprint remain available when full legacy decoding fails;
  unknown formats cannot become legacy; invalid/duplicate/nonobject/nonfinite
  JSON is rejected: passed.
- Existing tagged nonfinite/nested evidence and stored fingerprint survive;
  raw/production pools read identical TEXT through real migrated schema: passed.
- Codec remains pure representation, without clock, incoming fingerprint,
  SQL/HTTP/queue mutations or a competing execution authority: source inspection.
- Actual model-based evidence encoding/materialization through `model_of` or
  `model_of_json`, original-model fingerprinting, Run JSONB object insertion,
  real authorized Workspace/Project/Graph admission and consumer expiry/409
  precedence: **UNVERIFIED** by these fixture-based tests. The codec has no
  reachable runtime caller and this staged leaf does not authorize adding one.
- Full unchanged required CI, the dispatched `test: failure`, coordination
  approval and activation-policy resolution: **UNVERIFIED**. Focused/adjacent
  successes are not full-CI or rollout approval.
- No pre-fix/mutation claim: no source/test change was warranted in this round.
  Inventory counts are unchanged; no new inventory delta note is needed.

## Blocked handoff

**BLOCKED.** Only this report changed. No runtime, test, whitelist, quality ledger,
grant or gate was modified. The fresh provenance failure is not Vulture debt:
`quality/reachability-baseline.json` adds both modules and
`quality/reachability-dispositions.json` adds their dispositions without trusted
base authorization. The local Vulture exception cannot resolve that blocker.

Next: integration owner must resolve the trusted-base reachability restriction
under the two-merge policy (or coordinate the permitted integration slice), and
supply the exact current-head failing CI test/traceback before requesting another
source repair. Repeating unchanged green codec runs cannot discharge either gap.
This local evidence commit is a blocked handoff, never integration approval.

Progress: checked 1 issue; done 0 repairs; skipped 0; errors 1 reproduced provenance
blocker. No new scope started.

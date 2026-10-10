---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair — 46e5

## Frozen scope and starting evidence

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `8839ac3ad16222294fb200992ebc9ad0bd27a2c1`; supplied develop
  base `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. Starting tree clean.
- One item: issue #1893 admission codec repair. Candidate production/test files:
  `packages/maistro-core/src/maistro/tasks/admission_codec.py`,
  `packages/maistro-core/tests/tasks/test_admission_codec.py`; this note.
  `quality/vulture-baseline.json` only if the explicitly requested scan identifies
  retained debt requiring repair. Adjacent types, migrations, production callers,
  tests, ADRs and CI configuration are read/validation evidence only.
- No GitHub mutations, integration, activation, scheduler or policy changes.
- Dispatch evidence is frozen in job `46e53e7046fe4ceda154d2e7ff5bf428`.
  Driver logs: dependency sync, ruff check/format and inventory passed;
  focused tests reported 201 passed, 3 skipped, not DB durability proof.
- Prior job d26d reports binding repair already present, unauthorized reachability
  debt and a core CLI output-wrapping failure. These are allegations to recheck,
  not reasons to change gates or unrelated code.
- Ambiguity: historic issue coordination refs differ from the explicit assignment.
  Proceed only with local staged repair on the assigned exact head; no claim of
  integration authorization. Branch has unrelated differences from supplied base;
  do not modify or discard those differences.

## Results

Checkpoint: exact Vulture command passes (1326 findings / reviewed identities);
no ledger amendment is warranted. `RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` fails: new unauthorized reachability and
dispositions for `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`, judged against merge base `2a11c1cc006a`.
The CLI malformed-signing-key test reproduces its output-wrapping failure at
`packages/maistro-core/tests/extensions/test_cli_certification.py:287`.
Neither finding permits an in-scope codec or vulture-ledger repair.

Read repository instructions, accepted lifecycle ADR-081226-a66b and quality
provenance ADR-083126-5e62, the codec/types and adjacent tests, real migration
055 and CI ratchet arguments. The prior bound encode defect is already fixed
at codec line 290: `task_id` uses the existing binding's receipt identity.
Migration 055 requires exactly that mapping; this is not identity invention.
The leaf must remain representation-only. Candidate-local grants, dummy
imports or activation would contradict the issue/ADRs, not resolve the blocker.

## Final disposition: BLOCKED — validation complete, no speculative repair

Only this note changed. No source, tests, gates, grants, ledgers or runtime
wiring changed. The starting source SHA above is the tested source. Logs and
collected node IDs are preserved locally in `.pytest_cache/repair-46e5/` (ignored
validation artifacts, not committed); results are recorded here durably.

### Executed commands and results

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326/1326
  reviewed identities (`vulture.log`). No unbanked identity to repair.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: **failed**, exit 1
  (`provenance.log:21-30`), unauthorized dispositions/unreachable modules
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  `origin/develop` resolves to the exact supplied base; trusted merge base is
  `2a11c1cc006a977ee76281307767319773d4fb62`. Candidate banking is not approval.
- `uv run pytest
  packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key
  -x -q`: **1 failed**, exit 1 (`cli.log`). Assertion at line 287 expects
  `not a hex Ed25519 private key` contiguously; actual Rich output contains
  `not \na hex Ed25519 private key`. The command correctly exits nonzero on
  malformed input. This unrelated test is outside the assigned codec repair;
  its equivalence to the generic hosted `test` failure is **UNVERIFIED**.
- `createdb maistro_1893_46e5` and
  `DATABASE_URL=postgresql:///maistro_1893_46e5 uv run alembic upgrade head`:
  **passed**, real chain including 055 through 061 (`migrate.log`). New
  dedicated disposable local PostgreSQL DB; no schema imitation or stamping.
- With `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_46e5`,
  `MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_46e5` and
  `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-46e5/focused.xml`:
  **204 passed, zero skips** (`focused.log`). The same two paths with
  `--collect-only -q` collect **204 nodes** (`nodes.log`).
- All three real DB cases require a non-null production-codec pool and
  compare its DB/server identity with a separate raw pool. Production/raw
  backend PID pairs: **1486405/1486406** (unbound), **1486407/1486408**
  (bound), **1486410/1486411** (acknowledged), all on `maistro_1893_46e5`
  via the local socket. Each asserts **one** persisted scoped admission row,
  byte-identical TEXT and exact encoded/decoded mappings in both pools.
  Corrupt surrogate TEXT injected into each of three snapshot columns is
  rejected through both readers. Session evidence is in `focused.xml`.
- `psql postgresql:///maistro_1893_46e5 -X -c 'SELECT version_num FROM
  alembic_version; SELECT count(*) AS rows, count(DISTINCT generation_id) AS
  generations, count(DISTINCT run_id) AS bound_runs FROM task_idempotency;'`:
  **061; 0 rows / 0 generations / 0 bound runs** after test cleanup
  (`db-counts.log`). The disposable DB remains available for inspection.
- Process-local mutation under `uv run python` replaced the encoder with a
  wrapper setting `row['task_id'] = None`, then invoked
  `pytest.main(['packages/maistro-core/tests/tasks/test_admission_codec.py',
  '-q', '-k', 'test_v2_round_trip_preserves_all_snapshot_bytes'])`:
  **2 failed, 1 passed, 128 deselected**, expected exit 1
  (`binding-mutation.log`). Both bound states fail the independent storage
  assertion at line 134. No on-disk source changed. This verifies the existing
  repair's regression sensitivity, not a new fix.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`:
  **passed**, 3185 files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15860 nodes, no duplicates;
  this note's inventory delta is zero.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**.
  Candidate-local checks do not override the failed trusted-base gate.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src` confirms
  only the codec-to-types import and Vulture whitelist reference; no live
  consumer (`imports.log`). No full core/full repository run is claimed.

### Acceptance matrix

1. **V2 snapshot/mapping round trip**: unit and migrated DB tests pass in
   unbound, bound and acknowledged states. Fresh flat mapping asserted.
2. **Owner token storage-only hex**: strict canonical UUID tests and repr
   checks pass; DTO retains UUID, storage uses `.hex`.
3. **Legacy bound/unbound/partial**: pair with explicit receipt, absent pair,
   one-sided pair, missing receipt, receipt-only and unreadable evidence tests
   pass. Missing identities are not invented.
4. **Expired legacy header**: signed scalar evidence retained, no clock or
   expiry choice in this leaf; absent binding remains absent.
5. **Header expiry survives snapshot failure**: duplicate JSON decode fails
   typed while unchanged header survives.
6. **Header fingerprint survives partial binding**: stored fingerprint remains
   exact and is never recalculated.
7. **Unknown format fails closed**: seven unsupported discriminators and
   mismatched/header construction tests pass; no legacy fallback.
8. **Tagged nonfinite preservation**: all three evidence tag tokens survive
   without double decoding or fingerprint change. Actual model materialization
   through `model_of`/`model_of_json` is **UNVERIFIED**, not established by
   synthetic JSON fixtures.
9. **Strict JSON and safe failures**: duplicate/nonobject/bare nonfinite,
   overflow/lossy numeric evidence, nesting, Unicode and suppressed parsing
   chain tests pass, including corrupt TEXT from real DB readers.
10. **Raw/production pool equality**: three non-skipped migrated PostgreSQL
    cases above, independent sessions and exact SQL row counts.

Inspection confirms the frozen/slotted header, named scalar/storage fields,
strict int64s and UUID hex, #1851 constructors, ignored legacy completed_at,
header/full decode separation, and no assessment/SQL mutation/HTTP/queue
changes. Physical SQL `request` maps to DTO `request_snapshot`, as migration
055 specifies. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains
unchanged.

**UNVERIFIED / not implied by the passing leaf tests:** reachable production
consumer; explicit authorized Workspace/Project/principal and registered Graph
admission; end-to-end model materialization and Run JSONB object insertion;
live expiry/mismatch 409 precedence; activation/owner policy; unchanged full
required hosted CI. Synthetic fixture identities and direct admission-row SQL
are codec evidence, not authorization/transaction/dispatch evidence. Migration
upgrade was run; destructive downgrade/adoption tests were not run this round.

### Handoff

Resolve reachability through the separately coordinated real consumer or
separately landed trusted-base authorization, not vulture banking or fake
imports. No such authority is supplied to this repair worker. Route the concrete
CLI wrapping test failure to its owner and obtain the hosted failure traceback
before attributing the generic CI failure. Do not redispatch the unchanged
codec head for this same authorization blocker without new evidence/authority.

Progress: checked **1**, done **1 validation/handoff**, skipped **0 items**,
errors **2 unresolved checks** (provenance and unrelated CLI test). Next:
coordinated integration/authorization and CI test-owner repair. No merge,
activation, issue closure or remote mutation is authorized or performed.

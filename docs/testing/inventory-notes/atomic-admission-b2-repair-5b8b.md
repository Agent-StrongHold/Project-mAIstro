---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — 5b8b

Frozen scope: issue #1893 only, worktree `/home/dev/Git/wt/auto-1893`, starting
HEAD `adf1d2633eefa04a99dcebc3a2cc6c63f3741b44`, supplied develop base
`675db8be6c41b020ffffb224b2748c159c78a122`. Starting tree clean. No source or
ledger changes were warranted by the executed checks; this note is the only
repository change. No tests added or removed.

Read repository instructions, the frozen dispatch issue and prior result,
driver logs, codec, immutable types, adjacent tests and migration 055, plus
accepted ADR-081226-a66b and ADR-083126-5e62. Local repair authority does not
authorize activation, a new consumer, or candidate-approved debt. The canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model remains unchanged.

## Fresh evidence and commands

All source checks used the starting SHA above. Logs and collected node IDs are
in `/home/dev/maistro/jobs/5b8bc061f82a4a1c881d7f4e5e0519b7/worker-*`.

- Supplied `check-0.log` through `check-4.log`: dependency sync, ruff, formatting,
  focused tests and inventory pass, but tests are **201 passed / 3 skipped**.
  Those skips are not database proof.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 findings
  matching 1326 reviewed identities. No unbanked identity requires the permitted
  Vulture-ledger amendment.
- `RATCHET_BASE_REV=675db8be6c41b020ffffb224b2748c159c78a122 uv run python
  scripts/check-ratchet-provenance.py`: **failed**, exit 1. Trusted merge base
  `e46ad6708fda20f76b8915679ef701f3ddb6b7e2` rejects NEW reachability and
  disposition debt for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` (`worker-provenance.log:20-29`). This is not
  Vulture debt. Candidate banking cannot authorize it.
- Docker socket unavailable; native PostgreSQL verified accepting connections.
  `createdb maistro_1893_5b8b`, then
  `DATABASE_URL=postgresql:///maistro_1893_5b8b uv run alembic upgrade head`:
  **passed**, fresh disposable database migrated through the real chain,
  including 055, to 061. No stamping or SQLite substitution.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_5b8b` and `MAISTRO_REQUIRE_PG_LEGS=1`, ran
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/worker-focused.xml`:
  **204 passed, zero skips**. Same two files with `--collect-only -q`:
  **204 collected nodes**, saved in `worker-nodes.log`.
- Actual production/raw session PID pairs: **3367602/3367603** (unbound),
  **3367604/3367605** (bound), **3367606/3367607** (acknowledged). All are on
  `maistro_1893_5b8b` via local Unix socket. Each case requires non-null
  `pg_pool`, compares distinct sessions against the same DB, persists exactly
  **one scoped admission row**, and compares TEXT/DTOs through both pool codecs.
  Invalid escaped-surrogate evidence fails safely through both pools.
  Final SQL: revision **061**, **0 rows / 0 generations / 0 bound Run IDs**
  after cleanup (`worker-sql.log`). Database retained, no downgrade run.
- Process-local mutation replaces the encoder with a wrapper setting
  `task_id=None`, then invokes `pytest.main` on the codec file with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected exit 1,
  **2 failed, 1 passed, 128 deselected**. Both bound states fail the independent
  storage-shape assertion at `test_admission_codec.py:134`. Source unchanged.
- `uv run ruff check .` and `uv run ruff format --check .`: **passed**.
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15932 unique test identities.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, and `promotion-surface`:
  **passed**. Candidate ledger agreement does not supersede provenance failure.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  **1 failed**, line 287. Output wraps `not\na hex Ed25519 private key`,
  defeating a contiguous substring assertion. This is outside #1893; no
  unrelated source/test weakening attempted. Attribution to hosted
  `test: failure` is **UNVERIFIED** without its actual traceback.
- Source import search finds only codec-to-types and Vulture-whitelist
  references, no real production consumer. A passing unit test or export is
  not reachability.

## Acceptance review

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header, exact interfaces, named columns and fresh flat mapping | Source plus codec/identity tests pass. Physical `request` TEXT maps to the snapshot DTO per migration 055. |
| v2 round trip preserves snapshots and binding | Named unit test and all three real PG states pass; binding mutation fails both bound states. The encoder already uses the existing receipt identity at line 291. |
| Owner token is UUID hex only at storage | Named test and strict UUID/repr/error tests pass. |
| Legacy bound/unbound/partial distinctions without guessing | Named test plus missing-receipt, receipt-only, partial pairs and unreadable/whitespace evidence tests pass. |
| Expired legacy header does not invent identity | Named test passes; codec takes no clock. |
| Expiry survives malformed legacy snapshot | Named header test and invalid/duplicate JSON cases pass. |
| Fingerprint survives partial legacy binding | Named test passes; fingerprint is not recomputed. |
| Unknown format fails closed; supplied header must match scalars | Named format and scalar mismatch tests pass. |
| Tagged nonfinite snapshot evidence is preserved | Named synthetic nan/inf/-inf tests pass. Actual evidence-json/model_of/model_of_json model materialization with arbitrary program_context remains **UNVERIFIED**. |
| TEXT rejects invalid/duplicate/nonobject/bare nonfinite JSON | Named tests plus numeric precision, nesting and Unicode safety cases pass. Safe messages and suppressed parsing chains asserted. |
| Raw and production pool codecs agree | Three migrated PostgreSQL tests pass with real sessions, non-null pool and no skips. |
| No assessment/claim/HTTP/queue/fingerprint/authority changes | Source inspection and this note-only diff; staged leaf remains inactive. |
| Unchanged required CI and production reachability | **Not established**: trusted-base provenance fails; full hosted required CI **UNVERIFIED**. |

Authorized principals/Workspace/Project and registered Graph admission, Run
`json_of(run)` TEXT-to-JSONB object insertion, live expiry/409 precedence,
crash/transaction/dispatch guarantees, and migration downgrade/adoption remain
**UNVERIFIED** here. Synthetic codec DTO rows cannot prove those integration
contracts. No production activation or integration approval is claimed.

## Handoff — BLOCKED

The requested historical binding repair is already present and regression-
sensitive. Vulture is already green. The remaining exact-debt failure requires
coordinated genuine consumer wiring or separately landed trusted-base
reachability authorization, neither permitted in this codec-only repair.
Accepted quality provenance rules override any suggestion to bank away that
failure. Do not redispatch unchanged code as another Vulture repair.

Next: integration owner resolves the reachability/coordination prerequisite;
route the reproduced CLI assertion failure to its owner and obtain the hosted
test traceback before attributing it. No GitHub mutations, grant/gate edits,
new runtime authority, fake callers or discarded work.

Progress: checked **1** issue, done **1** validation/handoff, skipped **0**
issues, errors **2** unresolved checks (provenance and unrelated CLI test).

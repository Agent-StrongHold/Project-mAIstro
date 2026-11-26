---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair revalidation — 30fc8d1e

## Frozen scope and outcome

Only assigned issue #1893, branch `auto-1893`, starting source
`05d3e2f799f2b0d2a194c896823bf181309a9887`, supplied develop base
`af799688335f9a7dba7999a05e0e13f102c6c5ae`. Initial worktree clean.
Read repository instructions, supplied dispatch issue/PR evidence, previous
result, and driver `check-0.log` through `check-4.log`. No GitHub mutations,
ref refresh, activation, gate relaxation, or ledger/grant changes.

**BLOCKED, not an implementation repair claim.** The reported binding bug is
already repaired at the assigned head: `encode_admission_record` stores the
existing binding receipt as `task_id`, and the decoder rejects partial or
mismatched v2 binding. Fresh real PostgreSQL tests confirm compatibility with
migration 055. The named exact vulture scan passes: there is no unbanked or
removed identity justifying an amendment. The actual reproduced gate failure
is trusted-base reachability/disposition authorization for the two staged
modules, not vulture debt. This note is the only file changed this round;
no speculative source edit or extra test is used to manufacture a repair.

Local repair ownership is assumed from this explicit assignment, not from
historical coordination comments. Accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601 and 082826-d9f5 preserve the single execution spine, immutable
admission provenance and canonical store/consumer. Adding a fake caller to
pass reachability would violate both the staged issue scope and that model.

## Fresh executed evidence

Logs and full collected node IDs are retained under
`/home/dev/maistro/jobs/30fc8d1e4ea9457eb10af8f451ace7f2/`.
All commands below ran against the exact starting source; this commit changes
only this evidence note.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  **201 passed, 3 skipped** without DB environment (`focused-initial.log`).
  These skipped cases are not counted as durability evidence.
- Docker daemon was unavailable. Local PostgreSQL **18.6** was reachable;
  created dedicated disposable DB `maistro_1893_30fc8d1e` (no reused database).
  `DATABASE_URL=postgresql:///maistro_1893_30fc8d1e uv run alembic upgrade head`:
  **passed**, actual empty-to-head migration chain through **060**, including
  055 (`migrate.log`). No SQLite recreation or mocked schema. No destructive
  downgrade tests were run.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_30fc8d1e`, `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/focused-pg.xml`:
  **204 passed, no skips** (`focused-pg.log`).
  Production/raw backend PID pairs, same DB via local socket:
  unbound **2501485/2501491**, bound **2501528/2501540**, acknowledged
  **2501541/2501545**. Each case checked exactly **one persisted scoped row**,
  identical TEXT mappings and decoded records through both pools, and typed
  failure for corrupt surrogate evidence in every snapshot column. Each
  removed its row. Final SQL inspection: revision **060**, admission rows /
  distinct generations / distinct bound Run IDs **0 / 0 / 0**.
- Existing regression sensitivity, with a **process-local** encoder wrapper
  forcing `task_id=None` while retaining `run_id` (no source file mutation):
  `uv run python` calling `pytest.main` on codec tests with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes` produced exactly
  **2 failed, 1 passed, 128 deselected**. Both failures assert `None != rcpt-1`
  at `test_admission_codec.py:134` (`binding-mutation.log`). This is mutation
  evidence for the already-fixed defect, not a newly discovered source bug.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14623 passed, 986 skipped, 1 xfailed**,
  **55 warnings**, including aiosqlite callbacks after event-loop closure
  (`core-tests.log`). No DB environment supplied to this broader run; its
  skips are not durability proof. The supplied hosted `test: failure` was
  **not reproduced** by the changed-package suite; other packages/root-suite
  and full hosted CI are not claimed passing.
- Focused `--collect-only -q`: **204 nodes** (`focused-nodes.log`).
  `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, **15610 nodes**, zero duplicate
  evidence (`inventory.log`); no test-count delta this round.
  `git diff --check`: **passed**.
- `uv run ruff check .`: **passed**. `uv run ruff format --check .`:
  **passed**, 3166 files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, **1328 reviewed
  identities / 1328 findings** (`vulture.log`). No ledger amendment warranted.
- `uv run python scripts/check-<name>.py`, for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**.
  Candidate-local reachability/disposition scans report 171 unreachable
  modules; those passes are not trusted-base authorization.
- `RATCHET_BASE_REV=af799688335f9a7dba7999a05e0e13f102c6c5ae uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, exit 1 (`provenance.log`).
  Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  are NEW unauthorized unreachable modules and dispositions relative to the
  supplied trusted base. Candidate ledger changes cannot authorize them.

## Acceptance accounting and residual risks

All ten named prospective codec tests executed, including the real-pool
contrast, at the stated source. They cover immutable DTO round trips, storage
UUID hex and token redaction, distinct bound/unbound/partial legacy evidence,
header evidence despite expiry/full-decode failure, fingerprint preservation,
unknown-format rejection, tagged nonfinite JSON, malformed/duplicate JSON,
and raw/production TEXT compatibility. Additional existing tests cover signed
scalar validation, header mismatch, schema omissions, lossy numeric storage,
Unicode corruption, and partial/mismatched v2 binding. The decoder takes no
clock or incoming fingerprint and adds no claim decision or SQL mutation.

These are **codec/storage proofs**, not reachable admission-service proofs.
`admission_codec.py:51` explicitly documents its absent production consumer;
source search found identity imported only by the codec and vulture whitelist.
The DB fixtures use synthetic identity strings rather than authorized
Workspace/Project/registered Graph admission. End-to-end authorization,
`model_of`/`model_of_json` materialization, actual Run JSONB object insertion,
live expiry/409 ordering, activation, and full required hosted CI remain
**UNVERIFIED**. Dependency constructor normalization before encoding is not
repaired or independently certified by this storage-boundary validation.
Legacy bound pairs lacking receipt evidence remain explicit typed failures,
not invented canonical bindings.

Next owner action: coordinate the trusted integration base/production-consumer
and authorization path for the staged leaves; obtain the actual failing hosted
`test` traceback if separate from provenance. The vulture-only repair exception
does not authorize changing reachability ledgers/grants. No independent merge
or activation readiness is asserted.

Progress: checked **1**, done **0** repairs (revalidation complete), skipped
**0** issues, errors **1** reproduced gate failure. Work preserved; handoff
committed locally.

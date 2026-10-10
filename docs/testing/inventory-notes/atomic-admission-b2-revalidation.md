---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 CI-repair revalidation: blocked, not an activation claim

## Frozen scope and reconciliation

This round processes only issue #1893 in `auto-1893`, starting at
`515302a294ee8333ff83a4d4960b7cbd0dde1ce9`, with assigned develop base
`b78637f52be33c53d49aca1aa5738e3ab820aad3`. Both refs resolve; the worktree
was clean. The explicit writer assignment is treated as permission for this
bounded repair, not for production activation or other leaves' ownership.

Read repository instructions, the frozen dispatch's issue/PR/review evidence,
prior result, driver `check-0.log` through `check-4.log`, and accepted ADRs
081426-1f7c, 082526-7f02, 082826-b601 and 082826-d9f5. The canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` execution model and immutable
admission provenance remain unchanged. No scheduler, store, authorization
path, consumer wiring, gate, grant, or ledger is changed.

Only this inventory/handoff note changes in this round; no tests are added.
The reported old bound-row defect is already repaired at the starting head:
`encode_admission_record` writes `task_id = binding.receipt_id`, and full
decoding rejects incomplete or mismatched pairs. Migration 055 requires that
same shape. The driver passed 181 tests but skipped three PostgreSQL cases;
those skips were not accepted as database evidence.

## Executed validation

All commands below ran locally against the unchanged production/test source
at the starting SHA. Logs, collected node IDs, and JUnit properties are under
`/home/dev/maistro/jobs/cd6300eaf0f44f76af0f8e0c6888fce0`.

- Created the dedicated disposable database `maistro_1893_cd6300ea` on local
  PostgreSQL 18.6. `DATABASE_URL=postgresql:///maistro_1893_cd6300ea uv run
  alembic upgrade head` passed through the real migration chain to **060**
  (`migration.log`). No migration was stamped or recreated with SQLite.
- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_cd6300ea`, and `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/focused.xml`: **184 passed, no skips**.
  Same file selection with `--collect-only -q` records all **184** node IDs in
  `collected-nodes.log`.
- The raw/production pool tests persisted one row each and compared named
  TEXT columns and complete DTOs across different sessions on the same DB.
  Production/raw backend PID pairs were **2232588/2232624** (unbound),
  **2232630/2232634** (bound), **2232638/2232642** (acknowledged).
  `pg_pool` was non-None and used production `_register_json_codecs`.
  Each test removed its own row. The bound and acknowledged inserts exercised
  migration 055's constraint, not just encoder/decoder agreement.
- With the same required DB environment, `uv run pytest
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  **2051 passed, 3 skipped, 6 warnings** (`adjacent.log`). The warnings are
  aiosqlite worker callbacks after event-loop closure. Skipped tests are not
  durability proof. Final SQL counts after this broader suite: **3** admission
  rows, **0** distinct non-NULL generations, **2** distinct non-NULL Run IDs;
  this is adjacent legacy-test residue, not codec v2 rows (`db-counts.log`).
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  **3137** files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **15091** collected identities.
- Exact CI invocation: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed,
  **1328 reviewed identities / 1328 findings**, no unclassified finding or
  unmatched identity. No vulture ledger amendment is justified.
- `uv run python scripts/check-<name>.py`, separately for `reachability`,
  `reachability-dispositions`, `promotion-surface`, and `shipped-surface-truth`:
  all passed. These candidate-tree results do not override trusted-base checks.
- `RATCHET_BASE_REV=b78637f52be33c53d49aca1aa5738e3ab820aad3 uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, exit **1**. Its resolved
  merge base is `b1f17b8d6246`. Both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are new unreachable modules and new
  dispositions without already-landed authorization (`ratchet-provenance.log`).

## Acceptance evidence and unresolved boundaries

The focused suite exercises all ten named prospective codec contracts:
byte-preserving v2 snapshots, storage-only owner-token hex, distinct legacy
binding dispositions, expired-header identity non-invention, header expiry and
fingerprint survival, fail-closed unknown format, tagged nonfinite snapshots
without fingerprint recomputation, strict JSON rejection, and real migrated
raw/production TEXT pool equivalence. It also exercises schema/scalar/UUID
validation, safe typed failures, header/row matching, lossy numeric rejection,
nesting, whitespace identities, and fresh flat mappings.

There is no new regression test or source repair this round, hence no new
pre-fix failure claim. The supplied generic `test: failure` has no failing
node/traceback in the available evidence, and focused/adjacent tests do not
reproduce it. **UNRESOLVED**: need the actual failing job log/head before
changing code for that report. No guessed scanner finding or cosmetic source
change is substituted for a repair.

The codec is still an inactive contract leaf, with no production consumer.
No real authorized admission (explicit principals/Workspace/Project/registered
Graph), Run JSONB materialization via `json_of`/`model_of`, live expiry/409
precedence, dispatch/concurrency invariant, or full hosted CI acceptance is
proven here: those remain **UNVERIFIED**, not implied by mapping-level tests.

Two dependency findings were independently reproduced with `uv run python`
using the actual #1851 constructor (`dependency-reproduction.log`):
`CanonicalJsonObject('{"n":9007199254740993.0}')` still stores
`{"n":9007199254740992.0}`, and an escaped lone surrogate is accepted but its
canonical text raises `UnicodeEncodeError` when UTF-8 encoded. The storage
codec's existing lossy-number rejection cannot recover constructor-side loss
before encoding. These are dependency-owner repairs, not permission to expand
this B2-only scope or claim end-to-end snapshot preservation.

Disposition: **BLOCKED**. The exact-debt-ledger failure is trusted-base
reachability/disposition provenance, not an unbanked vulture identity. A fake
caller, test import, candidate authorization, or activation change cannot fix
it within this lane. Next: coordinated trusted-base authorization/consumer
integration, #1851 constructor remediation, and the missing failing test log.
Progress: checked **1**, validation done **1**, skipped issues **0**, failed
gates **1**. This note is a committed handoff, not integration approval.

---
inventory-delta:
  packages/maistro-core/tests: +20
---

# Issue #1893 bounded repair

Snapshot: assigned branch auto-1893, starting head
f9e5b5911afabbdc0cf1069cc35a3bc86f5e1937, develop base
b78637f52be33c53d49aca1aa5738e3ab820aad3. Clean worktree at entry.
Only issue #1893 is processed. Candidate repair files: admission codec, its
adjacent tests, this inventory note, and (only if scan demonstrates a need)
the explicitly permitted vulture identity ledger. Architecture/schema/CI files
are inspection-only. No activation, new execution authority, or grant edits.

Evidence inspected: dispatch-context.json primary issue, captured recent
comments and review findings; driver check-0 through check-4 logs. Driver logs
report lint/format success and 161 passed / 3 skipped; these are not real-DB
acceptance evidence. Earlier findings may be stale and will be rechecked.
Ownership assumption: this explicit lane assignment authorizes bounded repair
on the given branch, not independent activation or merge approval.

Current inspection: the earlier bound task_id repair is already present, as
are nesting and whitespace regressions. The requested exact vulture scan
passes (1328 reviewed identities / 1328 findings); no ledger amendment is
justified. The prior result identifies finite-number rounding in the #1851
constructor. B2 must not silently turn that rounded snapshot into an admitted
record. This repair will reject lossy normalization at the storage decoder
boundary, without modifying the separately owned constructor or inventing a
new snapshot format. Encoder inputs already constructed by #1851 remain a
separate dependency concern. Full integration readiness cannot be claimed.

Read accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601 and 082826-d9f5.
They retain immutable admission provenance and the single canonical execution
spine/consumer/store. No conflicting implementation is introduced.

Pre-fix evidence: `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
-q -k 'lossy_snapshot_numbers or exact_snapshot_numbers'` produced **12 failed,
4 passed**, at the starting production source with added tests. Each failure
was DID NOT RAISE: injected storage numbers were silently rounded (large
integer-valued decimals, high-precision fractions, underflow), across legacy
request and all three v2 snapshots. Log: job directory `precision-before.log`.
Tests deliberately bypass the already-normalizing DTO fixture.

Additional four negative nodes exercise an exponent outside Decimal's supported
range; it must also become a safe typed failure. Four positive nodes retain
ordinary decimal fractions, harmless notation changes, exact large integers,
and representable subnormal numbers. Total addition: 20 collected tests.

Intermediate validation: focused identity+codec suite **177 passed, 3 skipped**
before the extra four exponent cases. Targeted ruff check and mypy passed;
format check requested one line wrapping change, applied. PostgreSQL 18 is
available locally; created disposable `maistro_1893_634501aa`, migrated using
`DATABASE_URL=postgresql:///maistro_1893_634501aa uv run alembic upgrade head`
through the real chain 001–060. Migration log retained in the job directory.
An attempted read of `runs/pg/_codec.py` was not found; skipped (no file change).

## Final executed validation

All evidence below was executed in this worktree with the production/test
repair applied to the exact starting source. Logs and collected node IDs are
in `/home/dev/maistro/jobs/634501aaed2c4bb09e474dd18e1bc62a`.

- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_634501aa`, plus `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`: **184 passed,
  no skips**, including all three real migrated raw/production pool cases.
  Production/raw backend PID pairs: unbound **2015828/2015830**, bound
  **2015831/2015832**, acknowledged **2015833/2015834**, all on that same DB
  over the local Unix socket. Each persisted exactly one scoped row, checked
  identical TEXT mappings and complete DTOs, then removed its row.
- Same DB environment: `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **2051 passed, 3 skipped, 6 warnings**.
  Warnings are aiosqlite worker callbacks after event-loop closure; unrelated
  skipped tests are not durability evidence. See `adjacent-tests.log`.
  Final SQL inspection: migration **060**, **3** admission rows, **0** distinct
  non-NULL generation IDs and **2** distinct non-NULL Run IDs (adjacent legacy
  test residue, not v2 codec rows).
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3137 files. `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- Without DB env, `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **15091** nodes, **+20** this repair.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, **1328/1328**.
  No dead/unbanked identity or stale identity to fix; no ledger edit.
- Each via `uv run python scripts/check-<name>.py`: `radon-baseline` (138/138),
  `reachability`, `reachability-dispositions`, `promotion-surface`,
  `convergence-matrix`, `shipped-surface-truth`: passed.
- `RATCHET_BASE_REV=b78637f52be33c53d49aca1aa5738e3ab820aad3 uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**. The gate uses merge base
  b1f17b8d6246 and reports NEW unauthorized unreachable modules and dispositions
  for `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  This is not vulture debt. No grants, reachability ledgers or gates changed.

## Acceptance boundaries / handoff

The focused suite executes all ten named prospective codec contracts, including
actual migrated TEXT storage for unbound, bound and acknowledged records.
Header separation, safe typed errors, strict UUID/scalars, distinct partial
legacy evidence, fingerprint preservation and finite-number fail-closed
behavior are exercised. New regression tests fail against starting production
code for the stated reason, rather than accepting fixture-normalized numbers.

The codec remains intentionally inactive: it has no production caller. These
results are **not** production activation, admission authorization, concurrency,
Run JSONB materialization, live expiry/409 precedence, or full hosted CI proof.
Those integration criteria remain **UNVERIFIED**. Constructor-side precision
loss before encoding remains a #1851 dependency concern: this bounded B2
repair can validate original storage TEXT, not reconstruct already-lost input.
Direct `uv run python` reproduction at this repaired source still prints
`{"n":9007199254740993.0} -> {"n":9007199254740992.0}` from
`CanonicalJsonObject`; no dependency-fix claim is made.

Disposition: **BLOCKED** by trusted-base reachability authorization and remaining
integration/dependency acceptance. No speculative CI-test fix, fake caller,
ledger banking or activation has been used to conceal that. Next: coordinate
trusted integration base/consumer and #1851 snapshot constructor repair.
Progress: checked 1 assigned issue, bounded repair done 1, skipped 0 issues;
1 gate remains failed (ratchet provenance).

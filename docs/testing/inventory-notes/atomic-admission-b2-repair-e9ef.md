---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — e9ef

Frozen scope: issue #1893 only, branch auto-1893, starting HEAD
`9fe4037258fc1b18a30e9ec5e37aa2dd236f10d4`, supplied base
`d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`.
Inspect the existing admission codec, identity constructors, adjacent tests,
migration 055, relevant ADRs and CI scripts; change only evidence-backed codec
repairs, their tests, this note, and (if required by the exact scan) the explicitly
authorized vulture ledger. No reachability/grant edits or production activation.
Initial worktree clean; no incoming diff to salvage.

Driver logs inspected: dependency sync, ruff check and format passed; focused
identity/codec tests 201 passed, 3 skipped; inventory passed (15860 nodes).
These are not evidence of real PostgreSQL behavior. Prior artifact reports a
reachability provenance blocker; that result will be independently checked.

Assumption: the explicit assigned worktree/branch is the coordinated repair
surface; historic GitHub coordination text does not authorize activation or
changes outside this scope. Existing unrelated branch differences are preserved.

Checkpoint: the supplied bound-encoding finding is stale at this head:
`admission_codec.py:290` emits the existing binding receipt as `task_id`.
Existing tests independently assert migration 055's paired-column constraint.
Fresh exact vulture scan passed; no vulture ledger amendment is warranted.
Fresh provenance gate failed against the supplied base (merge base
`2a11c1cc006a977ee76281307767319773d4fb62`). Full diagnostics and remaining
acceptance validation follow below. Do not invent production wiring or modify
reachability grants to turn this staged leaf green.

## Final disposition: BLOCKED

Only this evidence note changed. No new tests, source changes, ledger edits,
authorizations, activation, or GitHub mutations. The generic hosted `test:
failure` has no supplied failing traceback; the local core suite does not
reproduce it. Existing branch differences outside this repair are preserved.

Read the supplied issue body, latest captured comments, PR #1945 review
findings, driver logs and previous result; inspected the codec, identity
constructors, adjacent tests, migration 055 and accepted ADRs 081426-1f7c,
082526-7f02, 082826-b601 and 082826-d9f5. Reconciliation: admission evidence
cannot invent execution identity, mutate admission provenance, or create a
parallel consumer/store. The explicit B2 scope excludes live consumer wiring;
adding an artificial caller to silence reachability would violate that scope.
The authorized vulture-ledger exception does not authorize reachability or
disposition grants. Resolving this prerequisite needs coordinated owner action.

## Commands and executed evidence

Source under validation: starting SHA above. Detailed logs and collected nodes
are under `/home/dev/maistro/jobs/e9ef6c19d5364cbc908c269dd823b638/`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 reviewed
  identities / 1326 findings (`worker-vulture.log`). Nothing unbanked or
  eliminated; an arbitrary ledger amendment would not repair this failure.
- `RATCHET_BASE_REV=d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1** (`worker-provenance.log`).
  Trusted merge base is `2a11c1cc006a977ee76281307767319773d4fb62`.
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each
  introduce unauthorized unreachable modules and dispositions. Other
  provenance subchecks pass. This is the actual remaining exact-debt blocker.
- Created dedicated disposable database `maistro_1893_e9ef6c19` using `createdb`.
  `DATABASE_URL=postgresql:///maistro_1893_e9ef6c19 uv run alembic upgrade head`:
  **passed**, fresh real chain through 061, including 055 (`worker-migrate.log`).
  No SQLite replacement, stamping, or destructive downgrade was used.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_e9ef6c19`, `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml`:
  **204 passed, no skips** (`worker-focused-pg.log`). Non-null production
  `_register_json_codecs` pool and independent raw asyncpg pool read identical
  TEXT values. Production/raw backend PID pairs: **790161/790162** unbound,
  **790245/790265** bound, **790267/790268** acknowledged, all same database
  on the local socket. Each asserted exactly **one persisted scoped row**,
  exact encode/decode mapping, and safe rejection of surrogate corruption in
  all three snapshots through both pools. Scoped rows cleaned by the tests.
- SQL verification via `psql postgresql:///maistro_1893_e9ef6c19 -X`:
  revision **061**; final admission row count / distinct generations /
  distinct bound Run IDs **0 / 0 / 0** (`worker-db-counts.log`).
- Process-local encoder mutation forced `task_id=None` without changing
  `run_id`; existing round-trip test via `pytest.main`, `-k
  test_v2_round_trip_preserves_all_snapshot_bytes`: **2 failed, 1 passed,
  128 deselected** (`worker-binding-mutation.log`). Bound and acknowledged
  states fail the independent migration-contract assertion at
  `test_admission_codec.py:134`. No on-disk source mutation. This proves
  regression sensitivity for the existing fix, not a new implementation.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14855 passed, 1004 skipped, 1 xfailed,
  56 warnings**, 290.17 seconds (`worker-core.log`). No DB environment for
  this broad run: its skips do not prove durability. Warnings include
  aiosqlite worker threads observing closed event loops and an unawaited fake
  process coroutine. No failing test was reproduced.
- Focused two-file `uv run pytest ... --collect-only -q`: **204 nodes**
  (`worker-nodes.log`). `uv run python scripts/check-suite-inventory.py
  --suite packages/maistro-core/tests`: **passed**, 15860 nodes, no duplicate
  evidence (`worker-inventory.log`). Inventory delta is zero.
- `uv run ruff check .`: **passed** (`worker-ruff.log`).
  `uv run ruff format --check .`: **passed**, 3185 files (`worker-format.log`).
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**
  (`worker-mypy.log`).
- `uv run python scripts/check-<name>.py`, names `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**
  (`worker-<name>.log`). Candidate-local success is not trusted authorization.
- Production import search (`rg -n 'admission_codec|admission_identity'
  packages/*/src --glob '*.py'`, `worker-imports.log`) finds no codec consumer;
  only the codec's type import and a vulture whitelist reference to the types.

## Acceptance accounting

The executed 204-node focused suite includes all ten named prospective tests:

- Exact immutable v2 snapshot round trips / fresh named flat SQL mapping:
  unbound, bound and acknowledged tests, including real migrated PostgreSQL.
- Owner token storage-only hex: token/UUID shape and redaction tests.
- Legacy bound/unbound/partial distinctions: partial pairs, receipt-only,
  pair without receipt, unreadable and whitespace evidence tests. No guessed ID.
- Expired legacy header without invented identity: scalar-preservation test;
  decoder receives no clock (expiry decisions remain outside this leaf).
- Header expiry despite snapshot failure: duplicate-snapshot test.
- Header fingerprint despite partial binding: changed stored fingerprint test.
- Unknown format cannot become legacy: seven discriminators and mismatched
  supplied header tests; missing columns are typed schema errors.
- Tagged nonfinite preservation without recomputing fingerprint: all three
  nonfinite tags; unknown request evidence survives canonical JSON storage.
- Invalid/duplicate/non-object/bare nonfinite JSON rejection: plus excessive
  nesting, numeric loss, Unicode corruption and suppressed exception chains.
- Raw versus production pool TEXT behavior: real migrated same-DB sessions,
  exact values and row counts above, not the value-level fake contrast alone.

Inspection additionally confirms frozen/slotted header, signed int64 checks,
constructor validation, ignored legacy `completed_at`, no SQL mutation,
HTTP/queue changes, assessment decisions or clock inputs in the codec.
The physical `request` column maps to DTO `request_snapshot`, consistent with
055; renaming the physical column to match issue wording would be incorrect.

**UNVERIFIED / not claimed:** reachable production admission integration,
real authorized principals/Workspace/Project/registered Graph admission,
end-to-end `model_of`/`model_of_json` materialization, actual Run JSONB object
insertion, live expiry/409 precedence, constructor normalization before the
codec boundary, activation, and full required hosted CI. Codec DB fixtures
contain explicit but synthetic identity strings, not authorization evidence.
B2 is a staged representation leaf; its passing tests alone cannot prove
these production outcomes or satisfy the trusted-base gate.

Handoff: obtain the actual hosted failing-test traceback; coordinate the
legitimate consumer/integration base or separately landed reachability
approval before retrying. Do not repeat vulture banking: that gate is already
clean and cannot authorize the remaining debt. Progress: checked **1**,
done **0 repairs** (validation complete), skipped **0**, errors **1 gate**.
This note is committed locally; no integration approval is asserted.

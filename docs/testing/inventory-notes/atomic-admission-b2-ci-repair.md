---
inventory-delta:
  packages/maistro-core/tests: +16
---

# #1893 bounded CI repair

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`1e8dc8d5a9f9a15d74350503b43e6b808cb62efb`, supplied develop base
`b1f17b8d6246d347f617fb2c0b969e6798e0152b`.
Evidence source: job `587c5d5cf05349398c49446ff871d098` dispatch snapshot and
check-0 through check-4 logs; no remote re-enumeration or mutations.

Frozen repair scope: admission codec, its task tests, this inventory note,
and (only if the required scan identifies reviewed retained debt) the permitted
vulture ledger. Read-only dependencies: immutable admission identity types,
real migration 055, runtime consumers, adjacent tests, ADRs and CI gates.
No changes to reachability/disposition grants, schedulers, admission policy,
or production activation are authorized.

Assumption: this writer assignment authorizes a local repair on the supplied
integration head, not merge/rollout approval. Prior findings and test claims
are unverified until rerun. The snapshot's latest comments retain a blocker;
do not infer that policy or ownership restrictions have been released.

Initial checkpoint: HEAD verified exactly; no incoming uncommitted work.
Validation checkpoint: supplied check logs pass lint/format/inventory; focused
suite in check-3 reports 145 passed, 3 skipped (no PostgreSQL proof). The
reported bound-v2 encoding defect is already repaired in the starting source.
Required exact vulture scan rerun: 1328 findings, all classified, exit 0; no
ledger amendment is justified. Provenance gate against the resolved supplied
base fails for the two unauthorized reachability/disposition additions
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.

Snapshot inline review evidence also identifies legacy whitespace evidence
being accepted and recursive JSON escaping the typed failure. Both remain in
the current codec; reproduce with regression tests before repairing these two
in-scope decode boundaries. Finite-number precision is a separate defect in
the read-only #1851 CanonicalJsonObject dependency; record rather than expand
this frozen repair scope. The codec remains unreachable in production (only
its own source declares its public functions); no fake caller will be added.

## Regression repair checkpoint

Before production edits, `uv run pytest
packages/maistro-core/tests/tasks/test_admission_codec.py -q -k
'excessive_snapshot_nesting or legacy_bound_evidence_rejects_whitespace'`
failed: **8 failed, 8 passed, 75 deselected**. Four legacy task-ID cases returned
a bound DTO for blank/padded identity. The first depth fixture (2000 arrays)
was insufficient to cause recursion failure in this Python interpreter and
incorrectly expected rejection; those four failures were fixture failures,
not regression evidence. Corrected to 10000 arrays after executing the real
constructor: depth 2000 accepted, depth 10000 raised RecursionError. The other
eight cases guard existing run/receipt rejection. Initial log:
`/tmp/1893-prefixed.log`; corrected pre-fix regression replay follows below.

Repair: reject whitespace evidence without trimming it and translate excessive
snapshot recursion to the safe `invalid_snapshot` error at the codec boundary.
No identity types, SQL or runtime consumer edits. Sixteen new collected nodes;
all use public header/full-decode entrypoints, preserve header evidence, and
exercise invalid originals rather than mocked results.

Read accepted ADRs 081226-a66b, 082526-7f02, 082826-b601, 082826-d9f5:
Goal -> Graph -> Run -> NodeRun -> Attempt remains canonical. A typed DTO is
not admission; these fixes add neither execution authority nor activation.
Migration 055 agrees with the existing v2 binding repair (task_id = receipt_id,
both task_id and run_id present or absent), so no reconciliation change needed.

## Executed validation (starting HEAD plus this repair)

- Corrected pre-fix replay: loaded `git show
  1e8dc8d5a9f9a15d74350503b43e6b808cb62efb:packages/maistro-core/src/maistro/tasks/admission_codec.py`
  into an isolated in-memory module and ran pytest on the two new tests
  (`-q -k 'excessive_snapshot_nesting or legacy_bound_evidence_rejects_whitespace'
  --tb=line`). **8 failed, 8 passed, 75 deselected**: now four actual leaked
  RecursionErrors and four accepted invalid task identities. No working-tree
  rollback or fake parser used.
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `createdb maistro_1893_587c5d5c`, then
  `DATABASE_URL=postgresql:///maistro_1893_587c5d5c uv run alembic upgrade head`:
  **passed**, new disposable local PostgreSQL database through the real chain
  001–060, including 055; no recreated schema or stamping.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both
  `postgresql:///maistro_1893_587c5d5c`, `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=/tmp/1893-repair-focused.xml`:
  **164 passed, no skips** (91 codec, 73 identity nodes). Both production
  registered-codec and raw asyncpg pools really insert/read all three v2
  binding states; snapshots remain TEXT and each full DTO equals its original.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15071 nodes (default env, +16).
- `uv run python scripts/check-radon-baseline.py`: **passed**, 138/138, no
  new, stale or regressed complexity identity.

Confirmed dependency limitation using `uv run python`: constructing
`CanonicalJsonObject('{"n":9007199254740993.0}')` returns
`{"n":9007199254740992.0}`. Snapshot finite-number precision acceptance fails
in #1851's float parser; no claim of arbitrary evidence preservation is made.
This requires coordinated dependency repair, outside this frozen codec scope.

- With the same PostgreSQL environment, `uv run pytest
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  **2031 passed, 3 skipped, 3 warnings** in 489 seconds. Skips do not count
  as acceptance; warnings are adjacent aiosqlite thread callbacks after loop
  closure, not codec failures.
- Final ruff check/format and two-file mypy reruns: **passed**. Exact vulture
  scan rerun: **passed**, 1328/1328; no genuinely dead or unbanked identity
  was found, so no ledger change is warranted despite the repair exception.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`,
  `check-shipped-surface-truth.py`, `check-convergence-matrix.py`: **passed**.
  These validate candidate consistency, not trusted-base authorization. The
  earlier executed provenance failure remains unresolved; no grant/ledger or
  consumer changes have been made to circumvent it.
- PostgreSQL production/raw PIDs from JUnit: unbound **1860260/1860261**,
  bound **1860262/1860263**, acknowledged **1860264/1860265**. All connected
  to `maistro_1893_587c5d5c` over Unix socket (address/port NULL), each case
  persisted exactly one scoped row and cleaned it afterward. After the broader
  suite, `psql ... -X` inspection finds migration **060**, **3** admission rows,
  **0** distinct generation IDs, **2** distinct Run IDs (legacy adjacent-suite
  residue, not new v2 admissions). No DB durability assertion uses a mock.
- `git diff --check`: **passed**.

## Acceptance and bounded handoff

Executed codec evidence covers the ten named prospective contracts: all three
v2 binding/snapshot round trips, storage-only owner-token hex, distinct legacy
unbound/bound/partial states, expired header with no invented identity,
expiry/fingerprint preservation despite failed full decoding, refusal of
unknown formats, tagged nonfinite snapshot/fingerprint preservation, invalid
and duplicate JSON rejection, and real raw/registered-pool TEXT equivalence.
The 16 new tests add safe recursion failure and whitespace-identity rejection.
UUID, signed scalar and header-mismatch cases also pass. This is typed codec
evidence, not a live admission or crash/transaction guarantee.

**Not proven / blockers:**
- `admission_identity.py:139-144` still rounds valid finite decimal evidence;
  arbitrary permitted program_context preservation is not satisfied.
- `check-ratchet-provenance.py` exits 1 against the verified supplied base:
  new unreachable modules and dispositions lack already-landed authorization.
  Fixing vulture cannot solve that independent gate.
- Production codec reachability, authorized Workspace/Project/principal/Graph
  admission, Run JSONB materialization through this slice, live expiry/409
  ordering and full hosted required CI are **UNVERIFIED**. The fixture IDs
  establish representation only, not authorization or model materialization.
  No C-consumer wiring or HTTP/policy change is allowed by this assignment.
- The dispatch's generic hosted `test: failure` contains no failing node/log;
  its exact failure is **UNVERIFIED**, not declared fixed merely because local
  focused and adjacent suites pass.

Changed files in this round: codec (two fail-closed boundaries), its tests
(+16 nodes), and this note. No baseline, grant, migration, prerequisite type,
or runtime authority edits. Verdict **BLOCKED**: repairs ready for handoff,
not integration approval. Checked: 1 issue; done: 0 acceptance-complete issues;
skipped: 0; errors: 1 blocking provenance command. Next: coordinated #1851
precision repair and trusted-base/integration ownership resolution. No new
items started; local commit preserves this partial repair.

---
inventory-delta:
  packages/maistro-core/tests: +38
---

# P1b Attempt cancellation-cause codec (#1885)

inventory-delta basis: `packages/maistro-core/tests` +36 collected node IDs,
true at the original branch base and still exactly +36 at the current head —
the develop sync moves that suite's total only through develop's own
recorded deltas, never this leaf's 36.

Lineage (all SHAs verified with `git merge-base`/`git show`):
- Original branch base `a586560170a9ce4d72ee7d750100d0178c1f69d0`: the leaf
  commit was authored here (pre-P1a; no `cancellation_cause` in
  `Attempt.model_fields`).
- Assigned develop base `ab8b3737fa64f8d840f421ef87ca506c509444ff`: P1a
  (#1884) is present — landed via #1928, commit `91996e192` — so the
  dependency block below is resolved at the base this leaf is judged on.
- Final head (this round): merge `4b6b92f6b` joining `431bb089b` (the leaf +
  its verification round) with `origin/develop` `2f56be40a` — the develop
  sync the driver preserved as a both-added conflict on the two leaf files.
  The conflict was resolved keeping this branch's versions verbatim: the test
  file stays the skip-gated `_HAS_P1A` variant (the only variant that runs
  honestly on pre-P1a checkouts; develop's no-skip variant from PR #2141
  stays on develop, and the skip-gated one supersedes it on merge-back —
  both variants collect and pass identically at this head, 36/34 live), and
  this note stays the long verification-round version. No content was lost:
  final leaf content = the two files in `ec986e182`, byte-identical
  (`git diff ec986e182 HEAD -- <test file>` empty).
- Historical final head: merge `44f16b483` joined the leaf commit `ec986e182`
  with the assigned base (conflict-free; the leaf adds two new files only).
  Its final leaf content is the same two files.

Production inputs at the current head `4b6b92f6b` (`git hash-object`):
`runs/evidence_json.py` blob `5a069112a0a1ffcf33888a912f21e88465f0f1c8` —
still byte-identical to the pinned audit at the original base;
`runs/model.py` blob `dab398a5387ae423bb28df5bdb29ee8bfb4cde51` — the sync
brings P1a's audited model/serializer changes from develop (expected; the
mutation sites `_serialize_attempt_without_unknown_cause` and the wrap
serializer registration at `runs/model.py:573` are intact);
`graph/durable_runs/types.py` blob
`8042c1ca5268e58d81cb4410f0f22988726e4866` — **no longer byte-identical** to
the pinned `943271b4...`: develop added
`RECOVERY_CLAIM_UNTIL_KEY = "recovery_claim_until"` (types.py:21). No claim
in this leaf depended on that file's bytes — the DurableRunRecord nesting
proof uses Run/NodeRun/Attempt lineage only. The leaf itself still touches no
production file.

## Dependency state (read this before interpreting results)

This leaf was DEPENDENCY_BLOCKED on #1884 (P1a optional
`Attempt.cancellation_cause` + null-dropping wrap serializer). That dependency
is now **resolved**: P1a is merged into the assigned develop base via #1928
(`91996e192`), `Attempt.model_fields` has `cancellation_cause`, and
`packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py`
is present. Historical pre-merge evidence: P1a's tested branch
`origin/feat/1884-attempt-cancellation-cause-model` @
`3ed42ca6c7f731988bcf5d95a4424b07a6f8d1d1`, where this file first ran 36/36.

The file still degrades honestly on any checkout that predates P1a: case rows
that cannot exist without the field carry
`pytest.mark.skipif(not _HAS_P1A, ...)` (`_HAS_P1A = "cancellation_cause" in
Attempt.model_fields`) with the reason "P1a (#1884) optional
Attempt.cancellation_cause is absent from this checkout". At the synced head
all 36 rows run live.

## What the 36 collected cases prove

`test_attempt_cancellation_cause_codec.py`, oracle nodes:
`test_cause_round_trips_through_canonical_evidence_json` (21 rows: causes
unknown/requested/recovered × transports payload-dict/str/bytes/bytearray/
decoded-dict/json-of-text/json-of-bytes), `test_unknown_cause_is_omitted_
without_dropping_other_none` (2), `test_nested_durable_record_preserves_
cause_and_lineage` (3), `test_cause_round_trip_preserves_nonfinite_physical_
evidence` (3), `test_codec_transport_shapes_preserve_identical_attempt` (3),
`test_invalid_cause_and_extra_fields_still_fail_after_decode` (4).

Assertions compare the wire exactly against a hand-frozen legacy baseline
(independently written dict + JSON text from blob `0de6b8ed9`, never generated
by the serializer), assert the unknown cause emits no key at root and nested
Attempt positions while every other explicit null and the empty metrics
mapping survive, round-trip a DurableRunRecord with true Run/NodeRun/Attempt
linkage, tag NaN/+Infinity/-Infinity in results/metrics and restore them
semantically via `evidence_values_equal` (not NaN == NaN), hydrate identical
Attempts from dict/str/bytes/bytearray inputs, and keep unknown values, wrong
types, non-CANCELLED typed causes and extra fields rejected after decode.

## Observed runs

- Pre-sync branch base `a58656017`: 36 collected, **15 passed, 21 skipped**
  (the P1a-gated rows), `uv run --frozen pytest ... -q -ra`. Reproduced
  independently this round before syncing.
- P1a branch `3ed42ca6c` (isolated scratch worktree, this file copied in
  unmodified): **36 passed, 0 skipped** (historical, pre-merge).
- Synced head `44f16b483` (leaf + assigned develop base, all rows live):
  **36 passed, 0 skipped**, and P1a's own
  `test_attempt_cancellation_cause_model.py`: **34 passed** — the issue's
  exact commands, `--frozen`, this round.
- `uv run --frozen ruff check` / `ruff format --check` on the leaf file: pass;
  repo-wide `ruff check .` and `ruff format --check .`: pass.
- `uv run --frozen python scripts/check-suite-inventory.py` after
  `uv sync --locked --extra dev --extra bootstrap` (CI's extras): ok, 17
  suites match, `packages/maistro-core/tests: 16396` = develop 16360 + this
  leaf's 36. (Without the bootstrap extra the two extension suites fail to
  collect — an environment gap, not drift; CI installs them.)

- Verification round (`b7c3bee8`, head `23f112446`, independent of the
  authoring rounds): all five issue commands re-executed — codec suite **36
  passed, 0 skipped**; P1a model suite **34 passed**; ruff check / format on
  the leaf pass; `scripts/check-suite-inventory.py` ok (17 suites, core
  16396 = 16360 + 36, collected without extra flags this time); collected
  IDs re-dumped and byte-identical to the list above; `git diff
  --name-status` vs `ab8b3737` shows the two leaf files, both `A` — no
  production delta. Two mutations re-applied and re-verified live at this
  head: unconditional cause pop → **20 failed** (exactly the typed rows);
  `encode_evidence` non-finite → `None` → **3 failed** (exactly the
  non-finite node); both production files restored byte-identical (`git
  diff` clean after each).
- This round (head `4b6b92f6b`, post-conflict-resolution): all five issue
  commands re-executed — codec suite **36 passed, 0 skipped**; P1a model suite
  **34 passed**; repo-wide `ruff check .` / `ruff format --check .` pass;
  `scripts/check-suite-inventory.py` ok (17 suites) after recording the
  develop sync's residual `tests/: +1` in `auto-1885-3733.md`; collected IDs
  re-dumped (36). Three mutations re-applied and re-verified live at this
  head: unconditional cause pop → **20 failed** (exactly the typed rows);
  `encode_evidence` non-finite → `None` → **3 failed** (exactly the
  non-finite node); `Attempt` `extra="forbid"` → `extra="ignore"` →
  **1 failed** (exactly `unexpected-extra-field`); both production files
  restored byte-identical (`git diff --stat` empty after each).

## Develop sync and the tests/ +1 drift

The sync brought `tests/` from 5210 (pre-sync base `ab8b3737`, verified by
collection in an isolated worktree) to 5261 collected node IDs. 50 of the 51
were recorded by develop's own notes (`1881-restore-oracle-snapshot-
consistency` +19, `l319-tool-version-reporting` +28,
`claude-ws-459-strict-m1-closeout-mode-and-a-named-pari-b993` +3); the 51st
— `tests/security/test_sentinel_permission_table_armed.py::test_hive_preset_tracks_the_executable_registry`
— was added upstream by `edb669149` (PR #1993) with no note on either
lineage, so the gate reported `DRIFT tests/: expected 5260, collected 5261`
at the merged head. Recorded as this branch's own residual delta in
`auto-1885-3733.md`; the drift pre-exists on develop `2f56be40a` (identical
`tests/` tree, baseline and notes), so that note also repairs develop's
latent drift when this branch merges back. No node was added, removed or
renamed on this branch. (Later re-derived to zero: develop's own
`1993-hive-permission-preset-inventory.md` arrived with the second sync
`6977e9161` recording the same +1, so this branch's duplicated block was
withdrawn — see `auto-1885-3733.md`.)

## Mutation evidence (each mutation applied, run, then restored byte-identical)

Independently re-verified again this round at the develop-synced head
`4b6b92f6b` (all 36 rows live; originals saved, restored by byte-copy,
`git diff --stat` on `packages/maistro-core/src/` empty after each — the
production tree is byte-identical to HEAD):

- wrap serializer pops the cause key unconditionally (`runs/model.py`
  `_serialize_attempt_without_unknown_cause`): **20 failed** — exactly the
  typed-cause rows across every node and transport.
- `encode_evidence` returns `None` for non-finite floats (`runs/evidence_json.py`):
  **3 failed** — exactly `test_cause_round_trip_preserves_nonfinite_physical_evidence[*]`.
- `Attempt` `extra="forbid"` → `extra="ignore"`: **1 failed** — exactly
  `test_invalid_cause_and_extra_fields_still_fail_after_decode[unexpected-extra-field]`.

Historical record from the authoring round:

On the P1a branch (all 36 rows live): serializer pops an unknown cause
unconditionally → 20 failed (exactly the typed rows); serializer registration
removed (child serializer bypassed, unknown emits null) → 10 failed (root and
nested unknown rows); wrap serializer applies global `exclude_none` →
32 failed (all payload-exact rows, node 6 untouched); `encode_evidence`
converts non-finite evidence to null → 3 failed (exactly the non-finite node);
Attempt `extra="forbid"` → `"ignore"` → 1 failed (unexpected-extra-field; the
other four rejections are semantic enum/type/lifecycle errors, correctly
unaffected).

On the pinned base (15 live rows): encoder passthrough → 1 failed
(`..._nonfinite_physical_evidence[unknown]`); `extra="ignore"` → 4 failed
(all four rejection rows). Production files were restored and verified with
`git status`/`git diff` after every mutation; the final diff adds the test
file, this note, and `auto-1885-3733.md` (the sync's residual `tests/: +1`
record) only.

## Scope

Test-only leaf: no production code, store, adapter, migration, lifecycle,
writer seam or producer-default change in the codec deliverable itself. Typed
REQUESTED/RECOVERED fixtures are model/codec inputs only and authorize no
writer. PG/SQLite JSONB round trips, archive cold hydration and SQLite reopen
remain separate persistence units in #232/#1151. Old-reader `extra=forbid`
incompatibility with non-null causes remains until the separately reviewed
cutover. The one production file this branch carries outside that boundary is
the `durable-events` CI-repair to `pg_audit.py` documented below — a gate
repair, not codec work, and proved against live PostgreSQL in the latest
round.

## 2026-10-20 CI-repair round (head `eb732ba7a`)

Assigned starting head `ad11cdf1a` (empty repair commit) was 508 behind
`origin/develop` `e20e9f52e`; the required develop sync was merged as
`eb732ba7aa50fc938816bc8aae1961c8fee45278`, conflict-free (`uv.lock` and
`quality/vulture-baseline.json` auto-merged; this note and the codec test kept
the branch's longer versions, no conflict markers left). Diff against
`origin/develop` at the merged head is exactly four leaf files — this note,
`auto-1885-3733.md`, the codec test and `uv.lock` (the pip-audit aiohttp/yarl
remediation) — i.e. zero production files. Production input blobs at this head
are unchanged from the previous record: `evidence_json.py`
`5a069112...`, `model.py` `dab398a5...`, `durable_runs/types.py`
`8042c1ca...`.

Two corrections were made to the test file in this round, and nothing else:

1. **PR #2228 review P2 (hollow suite): the `_HAS_P1A` skip gating is gone.**
   P1a is present on this branch's base (`Attempt.model_fields` carries the
   field, `attempt_cancellation_cause_model.py` is 34/34), so conditional
   skips could only hide a lost feature. All 36 rows are now unconditional.
   Fail-first evidence for the removal, applied to
   `runs/model.py` as a mutation (field + wrap serializer + CANCELLED-only
   validator removed, enum import left available — exactly the reviewed
   regression): **21 failed, 15 passed, 0 skipped**, and the 21 failures are
   precisely the rows that used to skip (`requested`/`recovered` rows plus
   `explicit-null`). Production file restored byte-identical
   (`git diff --stat` on `runs/model.py` empty) and the suite re-ran
   **36 passed, 0 skipped**.
2. Docstring/scoping prose updated to say the rows are unconditional.

Gate evidence at `eb732ba7a` (all re-executed this round, no earlier claim
reused):

- `uv sync --locked --extra dev` ok; `uv run ruff check .` "All checks passed";
  `uv run ruff format --check .` 3362 files already formatted.
- codec suite **36 passed, 0 skipped**; P1a model suite **34 passed**.
- `scripts/check-suite-inventory.py`: `ok: 21 suite(s) match` (32385 collected,
  0 duplicate evidence); this leaf's delta is still exactly
  `packages/maistro-core/tests: +36`.
- `scripts/check-test-duplicates.py`: ok, no byte-identical test files.
- vulture with CI's exact arguments and `RATCHET_BASE_REV=origin/develop`:
  rc=0, base `e20e9f52ea94` / candidate `eb732ba7aa50`, **1326 reviewed
  identities == 1326 findings**. No ledger amendment was needed or made.

Separately, the required `durable-events` gate was red at the start of
this round for a develop-side regression: `PgAuditLog.ensure_schema` issued
`ALTER TABLE audit_log ...` against a server that had never run migration
005, so container wiring crashed on the leg's fresh database. Repaired in
this round by making `ensure_schema` a no-op when `audit_log` is absent
(`packages/maistro-core/src/maistro/persistence/pg_audit.py`); the three
proof-column backfill statements and their exact SQL are unchanged, so
`test_ensure_schema_adds_proof_columns_idempotently` still passes. This is
the only production file touched by this repair round; the codec test and
its inventory delta are unchanged.

## 2026-10-20 second repair round (head `1e1086f9` → this commit)

The previous round's exception-based `ensure_schema` rewrite passed the
driver's focused checks but failed CI gates; this round repairs that
implementation and records the evidence:

1. **`ensure_schema` reimplemented on the canonical existence probe.** The
   interim version's `try: import asyncpg / asyncpg = None  # type: ignore`
   dance failed `mypy --strict` (`pg_audit.py:53: Unused "type: ignore"`, the
   exact `Quality / Mypy strict` CI failure) and its broad
   `except Exception` + error-message string matching classified failures by
   server message text. The replacement asks
   `SELECT to_regclass('public.audit_log') IS NOT NULL` before any ALTER —
   the same probe `maistro.runs.wiring`, `maistro.workspaces.wiring` and
   `maistro.container` already use — so no exception path exists to classify.
2. **Live PostgreSQL evidence, both directions (pgvector:pg18 containers,
   ports 15432):** with `ensure_schema` reverted to base (worktree at
   `e20e9f52e`), the durable-events leg against a fresh unmigrated database
   with `MAISTRO_REQUIRE_PG_LEGS=1` fails exactly as CI's pre-repair runs did:
   `asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not
   exist` (5 failed in `tests/events`). At this head the same fresh-database
   run passes **383 passed**; against the migrated database
   (`alembic upgrade head`) `test_pg_audit.py` is **21 passed, 0 skipped**
   (was 18 passed + 1 skipped), and without a DSN **19 passed, 2 skipped**.
3. **New tests (+2, recorded in this note's delta, now +38):**
   `test_ensure_schema_on_unmigrated_database_is_a_no_op` pins the unit
   contract (probe first, zero ALTERs when absent, no message-text
   classification) and
   `test_real_postgres_ensure_schema_tolerates_unmigrated_database` pins the
   real-server behavior (rename-away probe → no-op, restore → idempotent
   backfill, columns asserted via `information_schema`).
   `FakeConnection` gained a queueable `fetchval` double;
   `test_container_wiring.py`'s `_AuditFakeConnection` gained the same probe
   (its expected statement list now leads with it).
   **Mutation evidence (both applied and reverted byte-identical, verified
   with `git diff` after restore):** (A) probe removed so the method always
   ALTERs — `test_ensure_schema_adds_proof_columns_idempotently` and
   `test_ensure_schema_on_unmigrated_database_is_a_no_op` fail (2 failed,
   17 passed, 2 skipped); (B) probe inverted so the backfill never runs —
   the same two rows fail. The suite passes untouched in the clean state.
4. **Codec test: three `# type: ignore[attr-defined]` comments removed.**
   `Attempt.cancellation_cause` exists (`runs/model.py:543`); mypy with the
   repo's `strict = true` config flags the comments as unused
   `[unused-ignore]`. After removal the codec file's standalone mypy output
   matches its untouched sibling `test_attempt_cancellation_cause_model.py`
   (only the pre-existing `import-untyped` notes of a non-strict standalone
   run; CI's mypy gates check `src/` trees only, and both pass — see 5).
5. **Gate evidence re-executed this round:** `uv sync --locked
   --all-extras` ok; `uv run ruff check .` / `uv run ruff format --check .`
   green; `uv run mypy --strict packages/maistro-core/src` — **796 files, 0
   errors**; CI's full `lint-and-type-check` mypy argument set (all ten src
   trees) — **1066 files, 0 errors**; codec 36 + model 34 both passed;
   vulture with CI's exact arguments (`RATCHET_BASE_REV=origin/develop`)
   **1326 == 1326, rc=0**.

**Remaining red gates are inherited from develop, not from this branch**, and
are outside this lane's authority: `maistro.runs.admission_identity` (merged
to develop in #1936/`e20e9f52e` as an unwired #1851 contract leaf) is
unreachable-from-nothing debt with no `quality/reachability-baseline.json`
row and no landed reachability authorization. Verified at the base commit
itself in a detached worktree: `scripts/check-reachability.py` reports the
identical "1 module(s) are NEWLY UNREACHABLE" and exits 1; the root suite's
`test_reachability_baseline_identity.py`/`test_check_reachability.py` fail
the same three tests at base and at this head (full root run at this head:
**3 failed, 5393 passed, 138 skipped** — every failure is one of those three);
`scripts/check-ratchet-provenance.py` fails its reachability step with the
same identity as "NEW unreachable module absent from trusted base and not
previously authorized" (the `exact-debt-ledger` failure). The two-merge rule
(`scripts/ratchet_provenance.py`) means a candidate-side grant or baseline row
cannot authorize the debt — `load_authorizations` reads only the base — so the
repair is an owner-held grant plus baseline row on develop, as #1851's own
notes anticipated ("structural gates owner-held").

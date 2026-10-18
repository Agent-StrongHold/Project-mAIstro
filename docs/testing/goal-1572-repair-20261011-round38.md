# Issue #1572 repair — round 38 (2026-10-11, head 23e905d1e865)

Round 37 verdict (BLOCKED, external grant gap) was **not trusted** — every load-bearing
claim was re-executed first-hand at this head. No code, test, or ledger file changed in
this round; this note is the only edit.

## Snapshot

- head `23e905d1e865261de609587f29bb183ebb8d904e`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`
  (= `origin/develop`, re-fetched this round: still unchanged).
- Diff from round-36/37-validated head `e7e4d341b`: one docs file only
  (`git diff --stat e7e4d341b..HEAD` → `docs/testing/goal-1572-repair-20261011-round37.md`,
  150 insertions; `alembic/` and `packages/` diffs are **empty**), so prior first-hand
  migration/installed-base evidence carries to this head unchanged.

## The named CI red (test job) — re-proven to be the same single external grant gap

1. `uv run python scripts/check-execution-lifecycles.py` → **exit 1**, sole finding
   `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
   base and has no already-landed authorization` (19 → 20, baseline = base `3c761d14db94`).
2. `RATCHET_BASE_REV=origin/develop uv run pytest tests/test_check_execution_lifecycles.py -q`
   → **1 failed, 28 passed**; the failing test
   (`::test_the_shipped_ledger_matches_the_shipped_code`, tests/test_check_execution_lifecycles.py:374)
   is literally `gate.main()` against the real repository base — same single finding.
   All 28 gate-logic tests pass, so the gate implementation itself is healthy.
3. Two-merge rule confirmed in source: `load_authorizations` resolves the grant file
   **at the base revision** (`scripts/ratchet_provenance.py:504`,
   `resolve_baseline(path, base=base)`; rationale at lines 494–498: "a new grant does not
   take effect in the change that introduces it").
4. Base grant file has zero rows:
   `git show origin/develop:quality/ratchet-authorizations.json` → 0 rows, 0 GoalStatus
   mentions; `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` → empty.
   The branch correctly banks the classification in `quality/execution-lifecycles.json`
   (+4 rows) but cannot authorize itself.
5. Mechanical sufficiency re-proven at this head: loading the **unmodified** gate via
   `spec_from_file_location`, pre-seeding the `_ratchet_provenance` module cache with a
   `load_authorizations` that appends only
   `maistro.goals.model::GoalStatus` (exactly what a grant-only develop landing provides),
   then calling `gate.main()` → **exit 0**,
   `OK: 20 work-state vocabularies, all classified (3 CANONICAL, 8 CONVERGE, 7 DOMAIN, 2 PROJECTION)`.
   No in-branch edit can legitimately flip this gate; the sole unblock is the grant-only
   landing on develop — a GitHub mutation outside this lane's authority.

## Acceptance re-execution (fresh r38 databases, both majors)

- Fresh DBs `r38g18` (PostgreSQL 18.6) and `r38g17` (PostgreSQL 17.11) created and migrated
  `DATABASE_URL=... uv run alembic upgrade head` empty → `063`, single head both majors;
  catalog check: `alembic_version = 063`, `canonical_goal*` table count = **3** on both.
- Three-backend conformance with legs **enforced**
  (`MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/goals -q`):
  **70 passed** on pg18.6 and **70 passed** on pg17.11 (memory + sqlite + postgres legs,
  including append-only/CAS revision legs, subgoal lineage, run-binding immutability,
  wiring, restart readback). Note: the schema-agreement file requires
  `MAISTRO_TEST_DATABASE_URL` specifically; supplying only `MAISTRO_TEST_PG_DSN` errors
  by design (legs must not be silently skipped).
- M1 convergence freeze, CI's exact form:
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94...` → **exit 0**,
  "no unapproved new architecture island".
- Acceptance-state ratchet + mandate at the merge base, CI's exact form with PG legs
  available (fresh `r38ac` on pg18, migrated empty → 063):
  `MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=... uv run python scripts/check-ac-state.py
  --run-tests --ratchet --mandate 3c761d14db944a727fa0744444bc67cfe36d49f7` → **exit 0**;
  mandate 0 newly-claimed / 0 unproven, chain mandate 0/0/0.
  Operator error worth recording: the same command **without** the two PG vars exits 1 with
  `design_coverage: 39.641 falls below the floor of 44.2377` because PG-backed criteria
  whose tests skip lose the `passing` rung (`Criterion.rung`,
  scripts/check_ac_state_impl.py:213-222). Round 37's exit-0 claim reproduces only with the
  legs up; with them, this round reproduces it exactly. The misrun rewrote
  `quality/ac-state.json` byte-identically to the committed artifact (git status clean).
- Vulture per-identity ledger at CI's exact argv:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **exit 0**, 1323 reviewed = 1323 findings; no unbanked
  identity, **no ledger amendment warranted** this round.
- Driver deterministic checks (job cf6878954ab1402089fbe139b28fb6d0): `uv sync --locked
  --extra dev`, `ruff check .` (all checks passed), `ruff format --check .` (3288 files),
  targeted goals pytest 161 passed / 28 skipped (skips are the PG legs re-run enforced
  above), suite inventory ok (16334 unique identities). All exit 0.

## Inventory delta

None. No test added, removed, or moved; `docs/testing/inventory-notes/` requires no new
note for a docs-only commit.

## Residual action (unchanged, outside lane authority)

The sole remaining red is the GoalStatus execution-lifecycles authorization. Per the
two-merge rule it must land as a grant-only commit on develop first
(`quality/ratchet-authorizations.json` + prose owner/issue/reason), after which this
branch's already-banked `execution-lifecycles.json` row satisfies the gate — proven
mechanically above. This lane is prohibited from GitHub mutations; the branch itself is
otherwise merge-ready and left clean at `23e905d1e` + this note.

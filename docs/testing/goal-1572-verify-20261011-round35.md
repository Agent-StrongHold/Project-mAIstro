# #1572 round-35 independent verification at 5f75437d61a4 (2026-10-11)

Independent verifier re-execution. Base 435dc1937e0407ab4de198ffcced49860bb14ad2
(origin/develop, unmoved), head 5f75437d61a4ab3e3075deb9cc3a56bf12495cca
(origin/auto-1572, tree clean at start). No code, test, ledger or workflow
edits made; no inventory delta (no suites changed). This note is the round's
only artifact, committed per the writer rule.

## Acceptance re-executed first-hand (fresh round-35 databases)

- Fresh `r35v18` databases on both supported majors (pgvector pg18 / pg17,
  ports 55712/55717), migrated empty -> `063` with `alembic upgrade head`
  (`DATABASE_URL` per revision). Catalog check: `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` present on both.
  `alembic heads` = single head `063`.
- `uv run pytest packages/maistro-core/tests/goals -q` with
  `MAISTRO_REQUIRE_PG_LEGS=1` and both DSNs: **70 passed, 0 skipped** on pg18
  and pg17. Criterion -> test map read from collection:
  round-trip 3 backends; append-only + one CAS winner; lifecycle CAS with
  terminal-is-final; concurrent one-winner; subgoal lineage; recorded agent
  reassignment; foreign-goal == missing-goal; two principals isolated;
  admission binds goal_id/goal_revision; binding immutable after admission;
  half-binding refused; run outcome never moves goal state; Container exposes
  the store and seam; schema agreement migration-vs-ensure; restart readback.
- `uv run pytest tests/migrations -q` with
  `MAISTRO_TEST_DATABASE_URL` + `MAISTRO_REQUIRE_PG_LEGS=1`: **168 passed,
  0 skipped** per major. Includes `test_goal_installed_base_upgrade.py`:
  merged identities keep meaning (056/057 vs develop byte-identical —
  `git diff 435dc193..HEAD` on both files is empty), restored snapshots
  byte-identical, forward upgrades from the real develop merges
  `c560d4c` (at 056), `4675101` (at 057) and HITL `66f3cea` (at 061) with no
  stamp edit and no reset, upgraded base serves the durable Goal composition,
  plus fresh-install, reapplication-adoption, incompatible-column and
  foreign-shape refusal legs (criterion 13).
- `scripts/check-m1-convergence-freeze.py --base 435dc193...` exit 0.
- `scripts/check-ac-state.py --run-tests --ratchet --mandate 435dc193...`
  with `DATABASE_URL`/`MAISTRO_TEST_PG_DSN` exit 0: "every criterion this
  change declares is proven"; no chain debt added.
- Production wiring re-read in source: `container.py` wires
  `wire_goal_store(db_pool, pg_pool=pg_pool)` at :2414 and injects at :2701,
  seam `goal_reader`/`ScopedGoalStore` at :286; Hive
  (`backend/adapters/maistro_core.py:195`) and maistro-server
  (`main.py:344`) both compose through `create_container`, so the shipped
  Container-exposes test covers both compositions.

## The three merge-queue reds re-attributed (one external root cause)

1. Quality gate: reproduced at CI's exact invocation
   (`RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-execution-lifecycles.py`, quality.yml:1541; CI resolves
   `origin/develop` for PRs at :518-529) -> exit 1, sole delta
   `maistro.goals.model::GoalStatus`: "NEW work-state vocabulary is absent
   from the trusted base and has no already-landed authorization"
   (19 classified -> 20 discovered; no other failure listed).
2. Test job: `tests/test_check_execution_lifecycles.py::
   test_the_shipped_ledger_matches_the_shipped_code` re-run -> fails via
   `gate.main() == 1` with the identical GoalStatus delta (captured output
   matches the gate run in (1)).
3. Coverage job: structural cascade — the scripts-source producer runs
   `pytest tests/` (quality.yml:712-713), which includes the failing
   self-check from (2), and the combine step is `set -euo pipefail`
   (quality.yml:554-575). No third independent defect.

Branch-side repair is impossible by design: `ratchet_provenance.py::
load_authorizations` reads `quality/ratchet-authorizations.json` from the
base revision (:478-505), and the grant file is identical on branch and base
(`git diff 435dc193..HEAD -- quality/ratchet-authorizations.json` is empty;
zero GoalStatus rows on both sides). Per docs (AGENTS.md "a floor raise takes
two merges") the GoalStatus DOMAIN grant must land on develop first; only
then does this branch's ledger row pass. Disposition unchanged from rounds
27-34: grant-only develop landing is the sole remaining action; no on-branch
edit is legitimate.

## Gates re-run green this round (CI argv where applicable)

ruff check/format (driver check-1/2 + this round's suite runs), mypy 899
files clean, radon 137=137, reachability, wiring-reads, durable-table
inventory 112, workflow-inventory, promotion-surface, convergence-matrix,
agent-store-writes, contract-markers, vulture at CI's exact argv
(`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
1323=1323 unclassified 0 exit 0 — note the default no-arg scan banks rows
CI never sees and exits 1 (the documented trap; not a branch defect),
xenon at CI's package set 0 block/0 module violations vs baseline 145,
suite inventory 16334 unique identities (driver check-4).

Closure keywords: PR #1938 body says "Refs #1572" only; branch commit
messages contain no fixes/closes/resolves-with-issue-ref.

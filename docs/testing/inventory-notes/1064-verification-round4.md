# 1064-verification-round4

Round-4 independent re-verification at head `1b296fc65bfcc8ba6fca317b31cc65fd1b0a945b`
(base `0282be2423ab70480f15ebe585042c525c841ee9`, 61 commits; branch diff `39 files changed, 8133 insertions(+), 67 deletions(-)`).
Adds no tests; every claim below was re-executed fresh in this round, building on
the round-3 repair that merged `origin/develop` and renumbered the Evolve store
migration to `070`. Repo identifiers in this note were interpolated from the
filesystem by generator script, not transcribed by hand.

## Structural state (fresh checks)

- `git merge-base HEAD origin/develop` == `origin/develop` == `0282be2423` — the
  branch fully contains the develop tip it was reported CONFLICTING with; no
  sync conflict remains.
- `alembic heads` -> single `070 (head)`; `alembic/versions/070_evolve_domain_publications.py`
  carries `revision = "070"` / `down_revision = "069"` in the committed tree (the round-2 collision fix).
- Closure-keyword audit over all 61 commit subjects+bodies: zero matches for
  `closes/fixes/resolves #1064` (and no other closure keyword) — the PR stays open.
- Gate diffs vs base reviewed line-by-line, all additive or fail-closed:
  `quality/durable-table-retention.json` +26/-0 (ledger rows for ["evolve_domain_publications", "evolve_domain_snapshots"],
  each with `retention: "undecided"` and `deletion_path: null`);
  `scripts/check-diff-coverage.py` +3 (ADDS `packages/hive-conductor/backend/services` to
  `MEASURED_ROOTS`); `.github/workflows/quality.yml` adds the producer step
  "name: hive-conductor Evolve PostgreSQL legs (under coverage)" and fixes `coverage combine` -> `coverage combine --append`
  (plain combine had replaced the floor database the gate had just evaluated;
  the new code fails the job if the producer contributed no data). No gate weakened.

## Local battery (live PG container on port 5570, DSN maistro:maistro)

- `ruff check .` / `ruff format --check .` — clean (3655 files).
- `pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py -q` with
  `MAISTRO_TEST_PG_DSN` — **69 passed**, 0 skipped.
- `pytest packages/maistro-evolve/tests/test_domain_reconstruction.py
  packages/maistro-evolve/tests/test_durable_snapshot.py
  packages/maistro-evolve/tests/test_tournament.py -q` — **35 passed**.
- `pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -q` with
  `MAISTRO_TEST_PG_DSN` — **3 passed** (subprocess recovery child).
- `pytest tests/migrations -q` with `MAISTRO_TEST_DATABASE_URL` —
  **173 passed, 0 skipped** in 219.89s. (Caution for the next round: the
  migrations conftest keys on `MAISTRO_TEST_DATABASE_URL`, not
  `MAISTRO_TEST_PG_DSN`; the wrong variable silently skips 121 PG legs — the
  first attempt in this round did exactly that and was re-run correctly.)
- `pytest tests/cross_product_parity -q` — **26 passed**.
- `pytest tests/test_ci_quality_split.py tests/test_check_diff_coverage.py -q` —
  **114 passed**.
- `check-durable-table-inventory.py` — ok, 21/21 suites; `check-backlog-consistency.py` — ok.
- Vulture gate with CI's exact arguments (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`) — 1221 == 1221;
  `check-radon-baseline.py` 124 == 124; `check-reachability.py` (1503 modules / 82 unreachable)
  unchanged; `check-promotion-surface.py` ok; `check_direct_effects.py` all dispositioned.
- `mypy` per the AGENTS.md package list — clean in 961 source files.

## Substance re-confirmed (file:line, interpolated from the tree)

- Startup wiring: `evolution.py:290` then the `evolution.py:292` call, which re-arms the
  durable resolver in `evolution_graph.py`; fail-closed `EvolveRecoveryBlocked`
  raised at evolution_graph.py:57, evolution_graph.py:356, evolution_graph.py:586, evolution_graph.py:1587, evolution_graph.py:1595, evolution_graph.py:1638, evolution_graph.py:1644.
- Exactly-once fences: evolve_domain_store.py:390, evolve_domain_store.py:476, evolve_domain_store.py:706, evolve_domain_store.py:768 —
  `ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark) DO NOTHING`
  (the publication row's primary key IS the fence).
- Kill seam is the worst boundary the issue names: `test_evolution_restart_replay.py:75` — a wrapper
  delegates the domain mutation, then kills the process AFTER the durable
  journal row committed but BEFORE the in-memory finalize; recovered legs
  assert journal/tournament/population/fitness equality with an uninterrupted
  reference, byte-identity language at `test_evolution_restart_replay.py:1571`.
- Fresh-cycle non-suppression: `test_evolution_restart_replay.py:836` — after recovery, a NEW NodeRun
  pairing the same genomes publishes a NEW battle.
- Distinct-process recovery: `test_evolution_restart_replay_pg.py:586` is a real `subprocess.run` child;
  `test_evolution_restart_replay_pg.py:599` asserts a distinct OS process; `test_evolution_restart_replay_pg.py:601` pins
  `restore_kind == "admission"` plus ids/population/signature equality against
  the uninterrupted reference.

## Hosted / cross-repo (read-only)

- #947 review threads re-checked live via GraphQL this round: the ONLY
  unresolved thread is the P2 advisory "Record the durable executor on admitted
  Evolve runs"; all P1 threads are RESOLVED.
- Hosted CI settlement of `1b296fc65b` remains UNVERIFIED from the writer seat
  (no push rights); it is an integrator action, as recorded in round 3 and the
  repair round.

## Verdict

No repairs required this round; tree left clean and committed at `1b296fc65b`.

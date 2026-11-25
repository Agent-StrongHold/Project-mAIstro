---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# Evolve startup wiring measured; PG store joins the PostgreSQL coverage producer (#1064)

Live CI on the exact PR head (48939985c741) failed the
`Coverage gate (publish-set floor + diff coverage)` job: the diff-coverage
floor scored `services/evolution.py` at 72.2% and
`services/evolve_domain_store.py` at 85.2% of changed lines, while every
behavioral test passed against a real PostgreSQL server. Two measurement
holes, two fixes:

1. **Measurement (workflow, not a threshold change):** the `coverage-gate`
   producer runs the whole hive-conductor backend suite **without a server**,
   so the ten `MAISTRO_TEST_PG_DSN`-gated legs skip and
   `PgEvolveDomainStore` — the production exactly-once fence — scores as
   untested code. Per the rule the workflow itself documents (#231
   scheduling, #102 backlog, #12 personas, #1047 user model: *a new
   PostgreSQL store means an edit here, every time*), the
   `coverage (PostgreSQL)` job gains a producer step running the four Evolve
   suites (restart-replay, restart-replay-pg, domain-retention, domain-store)
   under `--source=packages/hive-conductor/backend` with the DSN set. No
   `--fail-under`, floor, or exempt list changed; this only adds measured
   scope. The store's `ensure_schema()` is `IF NOT EXISTS`, so sharing the
   job's migrated chain is safe, and the `requirements.txt` install is the
   job's last coverage run so a lock-external resolution cannot perturb the
   recorded maistro-core/canvas producers.

2. **Tests (service-free, +15):** the startup decision surface behind
   `restore_or_initialize_domain_state` had no direct cases for its honest
   fallbacks. `test_evolution_startup_wiring.py` (+13) pins
   `select_domain_store` backend honesty (owner pool → PgEvolveDomainStore,
   sqlite file URL → SqliteEvolveDomainStore, `:memory:`/non-sqlite/configless
   → `None`), `workspace_id` resolution from the canonical owner (resolved,
   configless, owner-unavailable), `attach_domain_store` guards (double
   attach ignored; attach over live domain state raises), and the restore
   fallbacks (no workspace key → fresh init; broken store → fresh init plus
   the public kind-only failure text; no snapshot → fresh init). The
   parametrized `test_backend_names_are_honest_about_durability` (+2) pins
   `InMemoryEvolveDomainStore.backend == "memory"` / sqlite — recovery trusts
   that name to mean cross-process durability.

3. **Advisory DevSkim alert resolved at source (behavior-preserving):** the
   anonymous `devskim` check failure was attributed and reproduced locally:
   it is the GitHub code-scanning result CheckRun (github-advanced-security
   app) fed by devskim.yml's SARIF upload, failing on one new PR-diff alert —
   DS148264 (non-cryptographic RNG) at the `random.Random(...)` constructor
   line this PR rewrote (`services/evolution_graph.py:342`). The local
   DevSkim CLI (1.0.90) reproduces it: DS148264 flags the seeded-RNG
   *construction*, and only lines carrying the reviewed
   `# DevSkim: ignore DS148264 until 2027-12-31` comment are suppressed —
   the shuffle line had the triage comment (#860), the new constructor line
   did not. A cryptographic RNG is not an option here: `SystemRandom` cannot
   be seeded, and deterministic pairing is this issue's own acceptance
   contract (replay-identical re-planning). The repair expresses the same
   seed logic in a form that fits the comment on the flagged line —
   `random.Random(self._pair_seed or None)` (identical semantics for the
   `str | None` seed: falsy → unseeded, truthy → seeded), carrying the same
   reviewed suppression as the shuffle line and develop's existing triage.
   Local CLI proof: `services/` scans clean (0 findings); ruff check/format
   accept the line (98 cols, SIM108-satisfying ternary preserved). The check
   remains advisory by the repo's own recorded policy
   (`.github/branch-protection.json`: "remains advisory until the owner
   explicitly adds it to the required merge contract"); this repair clears
   the alert instead of relying on that.

Validation in this repair round (all executed at this head):

- Backend four-file Evolve set with `MAISTRO_TEST_PG_DSN` on real pg18@069:
  32 passed, 0 skipped (before this change the same set skipped 10 legs);
  after the startup/devskim repairs the five-file set is 47 passed,
  0 skipped, including the 15 battle-receipt pinning cases and both
  byte-equality PostgreSQL legs.
- Full backend suite without a server (the coverage-gate producer shape):
  4398 passed, 56 skipped — re-run after every repair in this round.
- New tests: 25 collected across the two touched files, 23 passed + 2
  PG-skipped without a server.
- Local reproduction of the failing gate: combined no-PG backend suite +
  DSN-set Evolve producers + evolve/core sources under
  `scripts/check-diff-coverage.py --base f7b2456d23fd` → ok (was FAIL with
  the exact two files and 25/30 uncovered lines CI reported); re-proven
  after the devskim code repair.
- `uv run ruff check .` / `ruff format --check .`: clean.

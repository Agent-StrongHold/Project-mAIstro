---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 16: verifier-driven repair validation at 9814654bf

Verification-only round. No production or test code changed; resolves the
round-15 verify BLOCKED by converting its two open findings — "Docker daemon
unavailable, so PostgreSQL persistence validation is UNVERIFIED" and the
pre-radon-bank gate failure — into executed evidence.

## Radon gate (finding 1 — already banked at this head)

`uv run python scripts/check-radon-baseline.py` (CI's exact argumentless
invocation, quality.yml:738) exits 0 at head. The failure named in the round-15
findings predates `9814654bf` ("fix(quality): bank radon improvement for
InvocationExecutionService.invoke"), which lowers the recorded floor 12 -> 11
to follow #42's own `_resolve_provider` extraction down — a strict tightening,
no new debt granted. The gate still reports 1 "improved (baseline must shrink)"
finding: that comparison is against the *merge-base* ledger (5765efce8, which
still says 12); the candidate ledger matches the measurement, and improvement
deltas are non-blocking by design (only new/regressed blocks and unauthorized
raises exit 1 — scripts/check-radon-baseline.py:205-219).

## Vulture / quality gates

CI-exact invocations, all exit 0:

- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: 1359 findings vs 1359 reviewed identities,
  `unclassified: 0`.
- `check-promotion-surface.py`, `check-ratchet-provenance.py` (45 quality-JSON
  consumers carry provenance), `check-reachability.py` (181/1194 unreachable),
  `check-reachability-dispositions.py`, `check-credential-authority.py`,
  `check_direct_effects.py` (59 dispositioned call sites), `ruff check .`,
  `ruff format --check .`.

## PostgreSQL persistence (finding 2 — Docker unavailable; local PG 18.6 used instead)

Docker remains unreachable (`unix:///var/run/docker.sock`: connection refused,
`docker.service` not a unit), but the lane does not need it: a local
PostgreSQL 18.6 accepts both CI DSNs. CI's exact recipe (quality.yml:320-370)
was reproduced:

1. `MAISTRO_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/maistro_test
   uv run pytest tests/migrations -q` against the *unmigrated* database:
   **98 passed** (round 15 saw these skip: "13 skipped because
   MAISTRO_TEST_DATABASE_URL is unset").
2. `alembic upgrade head` to 050, then CI's schema-needing list
   (persistence, test_container_postgres, events, runs, graph, projects,
   workspaces, scheduling, tasks/test_idempotency_purge_driven,
   security/test_elevation_durable) with `MAISTRO_TEST_PG_DSN` +
   `MAISTRO_TEST_DATABASE_URL` + `MAISTRO_REQUIRE_PG_LEGS=1`:
   **4769 passed, 8 skipped, 0 failed** in 226s. `-rs` confirms all 8 skips
   are documented backend-applicability skips (e.g. "this backend enforces the
   rule with a foreign key, not a predicate"), none PG-availability.
3. Driver's focused set re-run with the PG legs enabled:
   **693 passed** (matches the count recorded in 9814654bf's message);
   focused #1169/#1170/#1194 suites (chat_attempt_recovery, execution_fencing,
   chat_execution/admission, consumer_claim_recovery, schedule_resume_lease,
   crash_window_invariants, execution_is_correlated, attempt_result_*,
   node_retry_attempts, typed_attempt_output, canonical_recovery_contract,
   cross_store_crash_reconciliation, recovery_disposition, runtime execution,
   governed_invocation): **328 passed**.
4. Spine PG leg ran for real: `test_spine_conformance.py -k postgres` = 123
   passed on live PG.

Honest error note: one intermediate run of `tests/persistence` right after the
migration suite showed 8 failed / 403 errors — self-inflicted run-order damage
(the migration chain's `empty_database` fixture leaves `public` dropped, and
persistence demands a *migrated* schema). Re-run after `alembic upgrade head`
is fully green (it is step 2 above). No code implication.

## Inventory + child issues

- `check-suite-inventory.py --suite packages/maistro-canvas/tests` -> 519 ok;
  `--suite packages/maistro-core/tests` -> 12152 ok. No delta.
- Read-only `gh issue view`: #1169 CLOSED, #1170 CLOSED, #1194 CLOSED — the
  acceptance clause "#1169/#1170/#1194 close before this issue completes" is
  satisfied on the child side.

## Residual (handoff, not code)

- PR body still reads only `Refs #42` (no auto-closing keyword). Editing the PR
  is a GitHub mutation this lane is prohibited from performing; the branch
  commits likewise carry no Fixes/Closes keyword, so closing #42 stays an
  explicit maintainer action after merge.

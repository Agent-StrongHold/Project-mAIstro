# Repair #1178 @ 33bd3f1ea (branch auto-1178) — 2026-10-20, CI-repair round

Re-derived every load-bearing check at the assigned head; no earlier claim assumed.
Worktree clean at start (33bd3f1ea); origin/develop == e20e9f52 == assigned base.

## Fixed this round (committed)

- **Supply chain (pip-audit) + ci.yml `security` — FIXED.** Local reproduction of the
  CI steps (`uv pip freeze --exclude-editable` → `pip-audit --strict --format=json`
  → `scripts/pip_audit_gate.py`) failed with three untriaged advisories:
  aiohttp==3.14.3 CVE-2026-111064 / GHSA-2g87-pp6c-29x5 / CVE-2026-111063, each with
  fix version 3.14.4 available. The gate's own instruction is "Fix by upgrading the
  dependency; only add to ALLOWED when no fixed version exists." Repaired via
  `uv lock --upgrade-package aiohttp` → aiohttp 3.14.5 (+ yarl 1.25.1), uv.lock only.
  Re-ran the gate at both `--extra dev` (ci.yml parity, 223 dists) and
  `--all-extras` (security.yml parity, 225 dists): rc=0, only the allowlisted
  ecdsa PYSEC-2026-1325 remains, direct-dependency usage OK.

## Verified green at this head (no change needed)

- Issue acceptance (all seven criteria): sole production Reactor construction is
  `services/foundation.py:189` `Reactor(state=self.state ...)`; state path resolves
  `settings.conductor_state_db` at :102 and builds the single `State` at :151.
  `test_reactor_writes_land_in_configured_state_db_only` (custom db respected;
  `assert not (data_dir / "state.db").exists()`),
  `test_reactor_and_persisted_store_writes_interleave_without_lock_errors`
  (200 forced interleavings, both path modes; no lock errors, no lost writes),
  `test_restarted_foundation_reads_the_same_reactor_log`, and the three
  `/health` persistence-authority tests (fire-and-forget + two unavailable
  variants) all pass through the real app/TestClient. Full backend suite
  3771 passed / 24 skipped; core reactor tests 21 passed; combined run 28 passed.
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: rc=0 (1326 reviewed == 1326 findings). The
  exact-debt-ledger CI failure is NOT vulture — see below.
- `mypy --strict packages/maistro-core/src` at `--all-extras` parity: Success
  (796 files). With `--extra dev` only, 5 import-not-found errors in
  `maistro/cli/_install.py`/`_builders_tui.py` are environment artifacts, not
  regressions.
- ruff check + format: clean. OpenAPI types drift check: regenerated
  `types.gen.ts` byte-identical (`git diff --exit-code` clean). Suite inventory:
  unchanged (no tests added this round).

## Owner-held structural blocker (unchanged, not repairable in this lane)

`maistro.runs.admission_identity` is NEWLY UNREACHABLE
(`scripts/check-reachability.py` rc=1). The module and its unwired status are
ancestors of the assigned base e20e9f52 (landed by the #1936/#1851 merge);
this branch touches zero `quality/` files, so the failure is inherited, not
introduced. It reds, by direct mechanism:

1. `Quality / Reachability` — the ratchet itself.
2. `exact-debt-ledger` — its FIRST step `check-ratchet-provenance.py` fails via
   `check-reachability-provenance.py` ("NEW unreachable module absent from
   trusted base and not previously authorized"); the vulture step passes.
3. ci.yml `test` — root suite: `test_check_reachability.py::test_baseline_matches_the_tree`
   + two `test_reachability_baseline_identity.py` tests (3 failed / 5393 passed).
4. `Quality gate (Pillars 1–4, 7, 8)` — aggregate needs-quality-reachability.
5. `Coverage gate` — its combine step runs the root suite as the `scripts`
   producer under `set -euo pipefail`; the 3 failures abort before coverage.xml.

Why not fixed here: `check-reachability-provenance.py` loads authorizations from
the merge base (`prov.load_authorizations("reachability", base=trusted_ref.base_sha)`),
so a grant + baseline row landed on this branch can never authorize themselves
(two-merge rule), and ledger/grant edits are outside this lane's permission
(exception: vulture-baseline.json only, and no vulture debt exists). Wiring the
module into production is #1851/#1845's declared follow-up and an
authorization-surface change — out of scope for #1178. Same disposition as the
round-221 note (repair-1851-9ddea59d.md): owner must land the reachability
authorization on develop, then a candidate banks the baseline row.

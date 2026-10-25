# REPAIR-NOTES — #49 round (branch `auto-49`)

Job `47222171c9804e449639153a60bbef1f`, 2026-10-25. Incoming head
`1fab9f4c4`; develop base for this round `09d56b6a0`. Two blocks carried in:
the preserved develop-sync conflict, and the red `test` job from the last
merge-queue evaluation (run 40184962631, job 121143712142).

## 1. Develop sync (the preserved conflict block)

The worktree arrived mid-merge with `MERGE_HEAD = 4f8811f92` (develop's
DevSkim triage #2111, carrying #2258/#2270/#2312/#2314/#2318) and one
conflict: `docs/architecture/CONVERGENCE-MATRIX.md`. Resolution, committed as
`62876ba03`:

- **Planning and wave orchestration row** — took develop's side: `none`
  unreachable with the `#2314` SPEC-255 annotation. The merged
  `quality/reachability-baseline.json` has no unreachable
  `maistro.orchestrator.*`/waves modules, so the claim is consistent with the
  ratchet the checker enforces.
- **Builders pipeline row** — kept this branch's side: the #459 scenario-1
  Builders → canonical Run → Conductor execution evidence
  (`tests/cross_product_parity`, cancelled mid-flight through the same id).
  This lane implements #49; the row's claim is proven by the suite itself.

`origin/develop` had advanced five more commits past `4f8811f92` (up to
`09d56b6a0`, EPIC M5-B); merged cleanly as `05fd45ec8` with no remaining
conflicts. `git diff --numstat origin/develop -- quality/` is empty — no
silent ledger row loss; the frontend-typed-client/image-pins/dispositions
deltas seen mid-merge were develop's own later commits arriving.

## 2. The red `test` job — actual root cause

The job log shows `RuntimeError('Event loop is closed')` blocks rendered as
`##[error]`, but those lines sit inside pytest **warnings summary** sections
(aiosqlite `_connection_worker_thread` raising after its loop closed —
`PytestUnhandledThreadExceptionWarning`). Every pytest step passed:

- maistro-server 645, turing 225, turing/backend 125, design 662,
  ext-harness 273, ext-sdk 147, root `tests/` 5653, hive backend 4034,
  cross-suite 10442 — all green at the pre-sync head.

The only real failure is the step after them:
`python scripts/check-suite-inventory.py` →
`DRIFT tests/: expected 5888, collected 5889` (net +1), exit 1. A suite
gained a node ID without a matching ledger entry — the branch's own earlier
state lagged develop's ledger, which #2334/#2336 and EPIC M5-B moved together
with the tests they added.

**Fix: the develop sync itself.** After merging develop through `09d56b6a0`
the ledger and the trees reconcile (every unfolded `inventory-delta` note on
this branch also exists on `origin/develop`; the branch's only test diff,
`tests/cross_product_parity/`, is node-count neutral):

```
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run python scripts/check-suite-inventory.py
→ ok: 21 suite(s) match the recorded inventory
```

## 3. Validation at the merged head (`05fd45ec8`)

- `scripts/check-convergence-matrix.py` — OK, 52 subsystems / 1469 modules.
- `scripts/check-suite-inventory.py` (full, 21 suites) — ok.
- `uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=60` —
  5800 passed, 139 skipped. One local-only failure
  (`test_every_quality_json_state_surface_is_classified_once` on
  `quality/ac-state.json`) is a **gitignored generated artifact** of
  `scripts/check-ac-state.py` (`.gitignore:86`) left by an earlier local run;
  moved to the job's `salvage/`, after which the test passes. CI checkouts
  never contain the file.
- `uv run pytest packages/maistro-core/tests/builders -q` — 201 passed,
  1 xfailed.
- `uv run pytest tests/cross_product_parity -q` — 26 passed (includes the
  real #459 scenario-1 Builders→Conductor execution).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1263 reviewed identities == 1263 findings,
  exit 0 (CI's exact arguments; no ledger amendment needed).
- `uv run ruff check .` / `ruff format --check .` — clean.
- `uv run mypy packages/maistro-core/src` — no issues in 830 files.

No test was added or removed in this round, so no new inventory note is
required; `docs/testing/inventory-notes/49-builders-canonical-cutover.md`
already records the lane's count-neutral parity-suite change.

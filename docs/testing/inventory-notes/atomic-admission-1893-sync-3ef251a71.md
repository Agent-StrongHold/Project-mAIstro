---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync + exact-debt-ledger re-validation round at 3ef251a71

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`8fc5d851fbbcc0e705d5d92d6d34e328e05578af`, briefed base `ab8b3737fa64`.
Worktree clean at entry, no incoming uncommitted work to salvage. Round type:
**develop sync** plus fresh re-execution of all three `exact-debt-ledger`
steps at CI argv and the acceptance battery on the merged tree. No source,
test, ledger, grant, gate or migration edits authored this round; no GitHub
mutations. The delta is 0: the +18 above is develop's own
`837-recovery-claim-window.md` (PR #2144) arriving with the merge; this round
adds no tests and must not double-count their note.

## develop sync

- `git fetch origin develop`: `refs/remotes/origin/develop` moved
  `07fac4abd807` → `498ff93a3cbf` (#2144 "fence recovery claims before
  reconciliation"), touching `graph/durable_runs/{attempt_executor,
  canonical_store,executor,types}.py` + 4 test files + CHANGELOG + its own
  inventory note. Zero overlap with the admission paths of this branch
  (`tasks/admission_codec.py`, `runs/admission_identity.py`).
- Merged `refs/remotes/origin/develop` into `auto-1893` → merge commit
  `3ef251a718e6`, conflict-free; `git diff 8fc5d851f HEAD -- quality/` is
  **empty** (no silent row loss per the AGENTS.md quality-merge hazard), and
  vs develop the quality delta is still exactly the branch's additive rows —
  10 `ratchet-authorizations.json`, 2 `reachability-baseline.json`,
  11 `reachability-dispositions.json`, 0 deletions.
- Fresh grant-state check: `grep -c admission` over
  `git show refs/remotes/origin/develop:quality/ratchet-authorizations.json`
  → 0; grant `6af21c54e` is still not on develop
  (`merge-base --is-ancestor 6af21c54e refs/remotes/origin/develop` → false).

## exact-debt-ledger at CI argv (workflow `vulture-ratchet.yml`, job `exact-debt-ledger`)

All three steps re-executed on merged HEAD `3ef251a718e6`; failure signature
unchanged from the prior round:

1. `uv run python scripts/check-reachability-provenance.py` → **exit 1**,
   failing on exactly `maistro.runs.admission_identity` +
   `maistro.tasks.admission_codec` ("NEW unreachable module absent from
   trusted base and not previously authorized"; 169 base → 171 candidate of
   1403 modules). Authorization is loaded **from the merge base only**
   (`scripts/ratchet_provenance.py` `load_authorizations`); the branch
   carries the owner-attributed grant rows for exactly these two identities
   (`quality/ratchet-authorizations.json` reachability section, owner
   @BlakeMatthews-dev, issue #1893, with matching CONNECT dispositions), but
   the base (develop, now at `498ff93a3`) still lacks them.
2. `uv run python scripts/check-shipped-surface-truth.py` → **exit 0**
   ("matrix is complete").
3. `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` (the driver-named
   command) → **exit 0**, `1322 reviewed identities -> 1322 findings`
   (exact match, zero unbanked identities). The lane brief's "amend
   quality/vulture-baseline.json" still has **no target** — the failing step
   is the provenance gate, not vulture, and nothing genuinely dead exists to
   delete: the two flagged modules are the issue's deliberate unwired B2
   deliverables.

Grant-first proof on the same tree:
`RATCHET_BASE_REV=6af21c54e uv run python scripts/check-ratchet-provenance.py`
→ **exit 0** ("53 quality JSON consumer(s) have explicit provenance"; 0
accepted/current lifecycle violations), i.e. the sole remaining ingredient
remains the owner-side landing of grant `6af21c54e` on develop per the
two-merge rule (a grant can never authorize the change that introduces it;
PR #1945's own review thread states the same). Branch-side escape valves
remain forbidden and were not taken: wiring the modules contradicts the
issue's "No production activation" and was tried and reverted as broken
(`29e3be4ab`, reverted at `0eacd9a44`); self-authorized ledger/gate edits
contradict the issue's "no baseline/grant/gate modifications to make an
unwired slice green".

## Acceptance battery on merged HEAD `3ef251a718e6`

- `uv run ruff check .` → exit 0 ("All checks passed!");
  `uv run ruff format --check .` → exit 0 (3302 files).
- Driver's focused five-file pytest (cli_lock, pack_contracts,
  attempt_cancellation_cause_codec, root_admission_identity,
  admission_codec) → **382 passed, 3 skipped** (skips = the three DSN-gated
  PG legs), matching the driver's own check-3.log on the pre-merge head.
- Suite inventory: `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → **exit 0**, collected 16621 == recorded
  (16603 prior + 18 from develop's `837-recovery-claim-window.md` note
  arriving with the merge), 0 duplicate identities/files.
- **PG durability re-proven live** on the merged head: fresh disposable DB
  `adm1893_r5` on the running pgvector:pg18 soak container
  (127.0.0.1:18433), full real migration chain `alembic upgrade head`
  001→063 exit 0 (`alembic current` = `063 (head)`), then
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
  uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → **204 passed, 0 skipped** (all three previously-skipped PG legs execute
  against the migrated schema with production `_register_json_codecs` pools
  plus the raw-codec contrast pool). Disposable DB dropped afterwards.
- `uv run mypy` at the ci.yml argv (ten `packages/*/src` targets) → exit 0,
  **1059 files**; `uv run mypy --strict packages/maistro-core/src`
  (quality.yml argv) → exit 0, **791 files**.

## Residual

`exact-debt-ledger` remains red for exactly one reason: grant `6af21c54e` is
not on the merge base (develop `498ff93a3`). Every locally executable
ingredient is green on this merged head; the failure is owner-side by
construction of the two-merge rule and cannot be repaired by any branch-side
edit without violating the issue's own constraints. No test was added or
removed by this round.

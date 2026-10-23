---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync + exact-debt-ledger re-validation round at 9059f6484 (job 9391b1423cc744deae031a7d9b0322f5)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`4ac5d34b77e82ebff75e50044d37cc2b0a6339e5` (= PR #1945 head), briefed base
`ab8b3737fa64`. Worktree clean at entry, no incoming uncommitted work to
salvage. Round type: **develop sync** plus re-execution of the one red job
(`exact-debt-ledger`) and the acceptance battery on the merged tree. No
source, test, ledger, grant, gate or migration edits authored this round; no
GitHub mutations. Driver-named gate argv re-run verbatim; driver-named
vulture amendment re-checked and reconfirmed to have no target.

## develop sync

- `git ls-remote` + `git fetch origin develop`:
  `refs/remotes/origin/develop` moved `ab8b3737fa64` → `07fac4abd807`, exactly
  one commit: `07fac4abd` (#2141, test-only — adds
  `packages/maistro-core/tests/runs/test_attempt_cancellation_cause_codec.py`,
  568 lines / 6 test functions / 36 collected nodes, plus its spec doc and its
  own inventory note `p1b-attempt-cancellation-cause-codec.md` claiming +36).
  Zero `quality/` changes on their side.
- Merged `refs/remotes/origin/develop` into `auto-1893` → merge commit
  `9059f6484e4d`, conflict-free (`ort`); diff vs pre-merge HEAD is exactly the
  two added files, zero deletions.
- Post-merge ledger-integrity check (AGENTS.md silent-row-loss hazard):
  `git diff --numstat refs/remotes/origin/develop -- quality/` is still
  exactly the branch's additive rows — 10 `ratchet-authorizations.json`,
  2 `reachability-baseline.json`, 11 `reachability-dispositions.json`,
  0 deletions; `git diff 4ac5d34b HEAD -- packages/maistro-core/src/` is
  **empty** (production src bit-identical to the previously PG-proven head).

## exact-debt-ledger at CI argv (workflow `vulture-ratchet.yml`, job `exact-debt-ledger`)

All three steps executed on merged HEAD `9059f6484e4d`:

1. `uv run python scripts/check-ratchet-provenance.py` → **exit 1**, failing
   on exactly `maistro.runs.admission_identity` +
   `maistro.tasks.admission_codec` in the reachability and
   reachability-dispositions delegated gates ("NEW … absent from trusted base
   and not previously authorized"). Mechanism re-derived in source:
   `scripts/check-reachability-provenance.py:70-72` resolves the trusted
   baseline and `load_authorizations(RATCHET, base=trusted_ref.base_sha)`
   **from the merge base only**; PR #1945 targets `develop` (GitHub PR data),
   so the base is origin/develop, which still lacks grant `6af21c54e`.
2. `uv run python scripts/check-shipped-surface-truth.py` → **exit 0**
   ("matrix is complete").
3. `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` (the driver-named
   command) → **exit 0**, `1322 reviewed identities -> 1322 findings`
   (exact multiset match, zero unbanked identities). The lane brief's
   "amend quality/vulture-baseline.json for reviewed retained identities"
   therefore still has **no target**; nothing genuinely dead to delete — the
   two flagged modules are the issue's deliberate unwired deliverables.

Grant-first proof on the same tree:
`RATCHET_BASE_REV=6af21c54e uv run python scripts/check-ratchet-provenance.py`
→ **exit 0** ("53 quality JSON consumer(s) have explicit provenance"; all
delegated gates OK), i.e. the sole remaining ingredient remains the
owner-side landing of grant `6af21c54e` on develop per the two-merge rule
(`docs/quality-gates.md`; `load_authorizations` reads base only, so a grant
can never authorize the change that introduces it). Fresh owner-state check
this round: `git merge-base --is-ancestor 6af21c54e refs/remotes/origin/develop`
→ false; develop tip now `07fac4abd` and the grant is still absent.

Branch-side escape valves remain forbidden and were not taken: wiring the
modules contradicts the issue's "No production activation" and was already
tried and reverted as broken (`29e3be4ab`, reverted at `0eacd9a44`);
self-authorized ledger/gate edits contradict the issue's "no baseline/grant/
gate modifications to make an unwired slice green".

## Acceptance battery on merged HEAD `9059f6484e4d`

- `uv run ruff check .` → exit 0 ("All checks passed!");
  `uv run ruff format --check .` → exit 0 (3302 files).
- Focused `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/runs/test_attempt_cancellation_cause_codec.py -q`
  → **237 passed, 3 skipped** (skips = the three DSN-gated PG legs at
  `test_admission_codec.py:470`; develop's newly merged 36 cancellation
  nodes all pass on this tree).
- Suite inventory:
  `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → **exit 0**, collected 16603 == expected
  (16567 prior + 36 from develop's own `p1b-attempt-cancellation-cause-codec.md`
  note, which arrived with the merge), 0 duplicate identities/files.
- **PG durability re-proven live this round** on the merged HEAD: fresh
  disposable DB `adm1893_r4` on pgvector:pg18 (`maistro-soak-pg`,
  127.0.0.1:18433), full real migration chain `alembic upgrade head`
  001→063 exit 0, then
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
  uv run pytest …test_admission_codec.py …test_root_admission_identity.py -q`
  → **204 passed, 0 skipped** (all three previously-skipped PG legs execute
  against the migrated schema with production `_register_json_codecs` pools
  plus the raw-codec contrast pool). Disposable DB dropped afterwards.
- `uv run mypy` at the ci.yml argv (all ten `packages/*/src` targets) →
  exit 0, 1059 files; `uv run mypy --strict packages/maistro-core/src`
  (quality.yml argv) → exit 0, 791 files after `uv sync --locked
  --all-extras` (the strict job's five initial `maistro_bootstrap.*`
  import-not-found errors were the documented missing-extras artifact, not
  code errors).
- Issue B2 interface conformance re-spot-checked in source on this tree:
  `admission_codec.py` defines `AdmissionDecodeCode` with exactly the six
  required StrEnum values (lines 127-135), `AdmissionRowDecodeError(ValueError)`
  (138), frozen `AdmissionRowHeader` (157), `decode_admission_header` (207),
  `decode_admission_record` (233); all ten prospective test names present in
  `test_admission_codec.py`.

## Residual

`exact-debt-ledger` remains red for one reason only: grant `6af21c54e` is not
on develop. Every locally executable ingredient is green on this merged head;
the failure signature is unchanged from the prior round and is owner-side by
construction. No test was added or removed by this round (delta 0).

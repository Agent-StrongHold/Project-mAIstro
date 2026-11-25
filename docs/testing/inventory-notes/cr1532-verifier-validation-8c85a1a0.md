---
inventory-delta:
  (none): 0
---
# Verifier round at merged head 8c85a1a0e1 (develop sync 8955cf07a2)

No test delta in this round: the only change is the develop-sync merge and its
conflict resolution in `quality/public-routes.json`, so the recorded inventory
is unchanged and this note carries a zero delta.

## What was resolved

Single conflicting file: `quality/public-routes.json` (`/v1/auth/register`,
`/v1/setup/`).

- `/v1/auth/register`: both sides chose `permanent`; took develop's reason text
  because it is accurate against the merged tree
  (`services/registration_policy.py` fail-closed durable policy, audited
  `PUT /v1/auth/registration/policy` at `routes/auth.py:1171`, hash-only
  invitation tokens redeemed by one conflict-safe insert, throttled since #366).
- `/v1/setup/`: dropped the registry row, keeping the branch's narrowing
  (`5746e76e8e`). Merged `middleware/auth.py` answers the prefix only inside the
  fail-closed pre-setup window (`_PRE_SETUP_PUBLIC_PREFIXES` +
  `_setup_complete()`), and `scripts/check-public-routes.py` counts exactly 11
  declared identities — develop's unconditional prefix row would fail as a
  stale entry.

## Executed evidence at 8c85a1a0e1

- `uv sync --locked --extra dev` — ok
- `uv run ruff check .` / `uv run ruff format --check .` — clean
- `scripts/check-public-routes.py` — ok, 12 -> 11 identities, base-authorized
- `scripts/check-adr-status-language.py` — ok, 0 findings
- `pytest tests/test_check_adr_status_language.py tests/test_check_adr_index.py -q`
  — 103 passed
- `pytest packages/hive-conductor/backend/tests/{test_auth_middleware,test_registration_policy,test_setup_first_run_questions}.py -q`
  — 128 passed
- `pytest tests/ -q --timeout=120` (REQUIRE_AUTH=false MAISTRO_DRY_RUN=1) —
  **6157 passed, 140 skipped, 0 failures** (6297 collected)
- `scripts/check-suite-inventory.py` (CI-exact, no args) — ok, 21 suites,
  36,587 node IDs, 0 duplicates
- `scripts/check-test-duplicates.py` — ok
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI-exact) — ok, ledger 1221 == scan 1221,
  no amendment needed
- `scripts/check-ratchet-provenance.py`, `check-contract-markers.py`,
  `check-merge-markers.py`, `check-image-pins.py`,
  `check-backlog-consistency.py` — all ok
- `maistro-registry lint . --strict` — 447 files, 0 errors, 0 warnings

## Sweep recount (prior drift finding)

Replicated the gate's exact parser (`_BODY_STATUS_RE`, front-matter strip,
`ADR-INDEX.md` exclusion) over `docs/adr` + `docs/specs` at base `bd96877e`:
**94 carrier documents** — matches the corrected "94" in
`ADR-092126-a28a` (lines 48, 82, 129), `ADR-INDEX.md:219`,
`CHANGELOG.md` `### Changed` entry (with the literal `(#1532)` marker), and
`tests/test_check_adr_status_language.py:96`. Head corpus: 0 findings (gate).

## Not assessable here

Hosted CI at this head is pending/out of scope for a local worktree; the
stale "root inventory 4,851" figure lives in the GitHub PR body text (it is a
historical figure from 8681590ec, documented as such in
`docs/testing/inventory-notes/1532-ordered-status-followup.md`) and cannot be
edited without GitHub mutation.

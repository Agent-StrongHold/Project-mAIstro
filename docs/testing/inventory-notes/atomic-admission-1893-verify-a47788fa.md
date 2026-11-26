inventory-delta:
  tests/: 0
  packages/maistro-core/tests: 0
---

# #1893 repair-round validation at a47788fa1 (no tree change)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`a47788fa135647f8576acd9125248f1ac08dc5a3`, worktree clean at entry. This
round makes **no source, test, ledger, grant or gate edits**; its only tree
change is this note. The lane brief's conditional vulture-ledger repair was
checked and is **not applicable**: the CI-exact scan is already exact
(1322 == 1322), so there is nothing unbanked to bank and nothing genuinely
dead to remove.

## Fresh evidence executed at a47788fa1

- Focused (issue command): `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` → **128
  passed, 3 skipped** (skips are the DSN-gated raw/production-pool leg; see
  the PG run below where they execute).
- PG durability, re-proven live, not trusted from earlier rounds: disposable
  DB `adm1893_1792226533` created on the dedicated PG 18.6 soak instance
  (`maistro-soak-pg`, 127.0.0.1:18433); real migration chain
  `DATABASE_URL=... uv run alembic upgrade head` → **001→063 exit 0**; then
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  → **131 passed, 0 skipped** (includes
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots`, which
  asserts production-vs-raw session identity: same database/server/port,
  distinct backend pids, `persisted_admission_rows == 1`).
- `MAISTRO_REQUIRE_PG_LEGS=1 ... uv run pytest
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` →
  **73 passed** against the same migrated DB.
- Environment artifact, diagnosed and resolved: `uv run mypy
  packages/maistro-core/src` initially reported 5 `import-not-found` errors
  for `maistro_bootstrap` because the driver's check-0 `uv sync --locked
  --extra dev` uninstalled the editable `maistro-bootstrap` package (see the
  job's check-0.log). CI's exact env is `uv sync --locked --all-extras`
  (.github/workflows/vulture-ratchet.yml); after that sync: **Success: no
  issues found in 791 source files**.
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3301 files already formatted.
- CI-exact debt gates (exact-debt-ledger job arguments):
  - `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
  - `uv run python scripts/check-vulture-baseline.py packages/*/src
    --min-confidence 60 --exclude '*/third_party/*'` → **1322 reviewed
    identities == 1322 findings, exit 0**; no unbanked identities, no ledger
    amendment made or needed.
  - `uv run python scripts/check-reachability.py` → exit 0 (171 unreachable
    of 1403 modules, all banked in the candidate baseline).
  - `uv run python scripts/check-reachability-dispositions.py` → exit 0
    (50 groups cover all 171; 149 CONNECT / 20 LIBRARY / 2 RETIRE).
- `uv run python scripts/check-suite-inventory.py` → **ok: 17 suites match
  the recorded inventory; 31451 collected == 31451 unique, 0 duplicate
  evidence**. Net inventory delta of this round: 0.

## Still red, and why it is not locally repairable

`RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` → exit 1, reproducing the two-merge
wall exactly: `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` are NEW unreachable modules / NEW
dispositions "absent from trusted base and not covered by an already-landed
reachability authorization". The authorizing grant is commit `6af21c54e` on
this branch; `load_authorizations` reads `quality/ratchet-authorizations.json`
from the merge base, and a fresh fetch shows origin/develop still at
`ab8b3737fa64`. No local edit can fix this: removing the grant/baseline/
disposition rows makes `check-reachability.py` fail on the same two modules
(the codec is deliberately unwired until the C consumer leaf — the issue
forbids wiring it), and keeping them requires the grant to land on
origin/develop first, which is a push outside this worker's authority. This
also still needs owner adjudication against the issue text "no
baseline/grant/gate modifications to make an unwired slice green": the rows
follow the repo's documented CONNECT pattern for deliberately-parked modules
(precedent: `mutation-testing-tooling` disposition on develop; the
`_vulture_whitelist.py` "contract ships first by design" posture), but the
strict issue reading conflicts and only the owner can reconcile the two.

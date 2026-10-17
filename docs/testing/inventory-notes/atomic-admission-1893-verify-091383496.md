inventory-delta:
  tests/: 0
  packages/maistro-core/tests: 0
---

# #1893 verification round at 091383496 (no tree change)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`091383496d1f873f17bae13cf34ed9c9ce99333e`, worktree clean at entry. This
round makes **no source, test, ledger, grant or gate edits**; its only tree
change is this note. Trigger for the round: the merge-queue evaluation named
`test: failure`; the captured CI data for head `a47788fa` shows the `test`
check **success** and `exact-debt-ledger` **failure**, so the named gate is
stale and the real failing gate is the provenance one documented below.

## Fresh evidence executed at 091383496

- Focused (issue command): `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` → **128
  passed, 3 skipped** (the DSN-gated raw/production-pool leg; see PG run).
- PG durability re-proven live on a **new** disposable DB `adm1893_v7391`
  (dedicated PG 18.6 instance `maistro-postgres`, 127.0.0.1:5433): real
  migration chain `DATABASE_URL=... uv run alembic upgrade head` →
  **001→063 exit 0**; then `MAISTRO_REQUIRE_PG_LEGS=1
  MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=... uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
  **131 passed, 0 skipped**; `... tests/runs/test_root_admission_identity.py
  -q` under the same env → **73 passed**.
- `uv sync --locked --all-extras` (CI's exact env, vulture-ratchet.yml:75),
  then `uv run mypy packages/maistro-core/src` → **Success: no issues found
  in 791 source files**. (The driver's `--extra dev` sync uninstalls
  `maistro-bootstrap`; its mypy import errors are an env artifact, not code.)
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3301 files already formatted (driver logs check-1/check-2, this head).
- CI-exact debt gates (exact-debt-ledger job arguments):
  - `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
  - `uv run python scripts/check-vulture-baseline.py packages/*/src
    --min-confidence 60 --exclude '*/third_party/*'` → **1322 reviewed
    identities == 1322 findings, exit 0**. The lane brief's conditional
    vulture-ledger amendment is **not applicable**: nothing unbanked, nothing
    genuinely dead to remove; no amendment made.
  - `uv run python scripts/check-reachability.py` → exit 0 (171 unreachable
    of 1403, all banked); `scripts/check-reachability-dispositions.py` →
    exit 0 (50 groups: 149 CONNECT / 20 LIBRARY / 2 RETIRE);
    `scripts/check-promotion-surface.py` → ok;
    `scripts/check-suite-inventory.py` → ok, 17 suites, 0 duplicate
    evidence. Net inventory delta of this round: 0.
- Diff scope re-checked: `git diff --name-only ab8b3737...HEAD` contains no
  alembic/server/queue/http/router paths — src changes are exactly
  `maistro/tasks/admission_codec.py`, `maistro/runs/admission_identity.py`,
  `_vulture_whitelist.py`. `admission_codec` is imported by no production
  module (grep over `packages/*/src`), matching the reachability ratchet and
  the issue's "C is the consumer" boundary.

## Still red, and why it is not locally repairable (unchanged from a47788fa)

`RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` → exit 1:
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec` are NEW
unreachable modules / NEW dispositions "absent from trusted base and not
covered by an already-landed reachability authorization". The authorizing
grant is commit `6af21c54e` **on this branch**; `load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base by design
(scripts/ratchet_provenance.py:478-502: "a new grant does not take effect in
the change that introduces it"), and a fresh fetch shows origin/develop still
at `ab8b3737fa64`. No local edit fixes this: deleting the rows fails
`check-reachability.py` on the same two modules (the codec is deliberately
unwired until the C leaf), and pushing the grant to develop is outside this
worker's authority. Separately, all 684 issue comments were searched: no
owner adjudication exists of the grant-rows-vs-issue-text conflict ("no
baseline/grant/gate modifications to make an unwired slice green"). Both
items need owner action, not another repair round.

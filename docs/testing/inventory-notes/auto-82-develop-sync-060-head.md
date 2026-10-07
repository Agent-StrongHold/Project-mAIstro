---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: origin/develop 28614700bd9 (4 commits) merges clean at eff5187a0, chain head stays 060

Sync round merging `origin/develop` (`28614700bd9`, four commits past this
branch's previous base `feb19affc`: #2036 role='switch' accessible name,
#338 chat admission compensation, #2040 implemented-route navigation entries,
#2039 PyJWT dependency floor plus the new
`scripts/verify-minimum-dependencies.py` gate) into auto-82 at `c8240a7c3`.
Merge committed as `eff5187a0`, **conflict-free** — no overlapping file with
the branch's own delta (alembic docstrings, docs, quality ledgers,
tests/migrations). No test was added or removed **by this branch**; the
incoming suites are develop's own commits, which carry their inventory
evidence with them. `scripts/check-suite-inventory.py` reports **17/17
suites matching** the recorded baseline at the merge.

## Why this round exists

The fourteenth addendum's residual ("the branch is 7 commits behind
origin/develop — the next queue evaluation may require a fresh develop sync")
came due: the merge-queue base moved from `feb19affc` to `28614700bd9`. Per
the documented procedure the branch merges origin/develop rather than
awaiting the queue.

## Merge content and impact

- **No migration-chain impact:** none of the four commits touches
  `alembic/`; `uv run alembic heads` at the merge → single `060 (head)`.
- **No quality-ledger impact:** no `quality/*.json` on the incoming side;
  `check-vulture-baseline.py` with CI's exact args
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  `RATCHET_BASE_REV=origin/develop`) **exits 0** — 1328 reviewed identities
  = 1328 findings against base `28614700bd9`.
- **`uv.lock` delta is floor metadata only** (`pydantic >=2.7.0`,
  `pyyaml >=6.0.1` requires-dist lines); the resolved set is unchanged
  (`pyjwt==2.15.1` before and after), confirmed by an empty
  `uv pip freeze --exclude-editable` diff across the merge.

## Post-merge battery, all green at `eff5187a0`

- `ruff check .` clean; `ruff format --check .` **3147 files** clean.
- `check-suite-inventory.py` OK (17/17 suites match).
- `mypy packages/maistro-core/src` clean — 768 files, exit 0. (With only
  `--extra dev` installed, mypy reports 5 `import-not-found` errors for
  `maistro_bootstrap.*` in `cli/_install.py` / `cli/_builders_tui.py` —
  files this round does not touch; installing `--extra bootstrap` clears
  them. Environmental, not a merge regression.)
- **Supply chain re-proven at the merged tree with CI's exact commands:**
  `pip-audit --strict --format=json -r <freeze>` reports exactly the 2x
  `ecdsa PYSEC-2026-1325` pair triaged in `scripts/pip_audit_gate.py`'s
  `ALLOWED`; the gate **exits 0** ("pip-audit OK (1 known, all triaged in
  ALLOWED); direct-dependency usage OK: 11 packages, 62 runtime
  dependencies, 4 reviewed dispositions").
- **develop's new gate proven with CI's exact args:**
  `python scripts/verify-minimum-dependencies.py --package
  packages/maistro-core --python 3.12` **exit 0** ("24 check(s) passed
  (pyjwt resolved 2.14.0; all 12 declared dependencies at their floors);
  PyJWT-removal refusal intact").
- **Incoming/adjacent suites at this head:**
  `packages/maistro-core/tests/runs/test_chat_admission_compensation.py` +
  `test_container_chat_runs.py` **81 passed / 12 skipped**;
  `tests/test_verify_minimum_dependencies.py` +
  `tests/test_ci_merge_group_scope.py` **56 passed**;
  `packages/hive-conductor/backend/tests/test_backlog_routes.py` **36
  passed**; `packages/maistro-server/tests/api/test_backlog_history_api.py`
  **6 passed**; `packages/maistro-core/tests/fitness/test_principal_identity.py`
  **1 passed** (with `scripts/check-principal-identity.py` and
  `scripts/check-route-permissions.py` both exit 0 — re-landed P0.1/P0.2
  enforcement, see the fifteenth addendum of `82-backlog-work-source.md`).
- **Backlog substrate at this head (local PG 18.6, pristine scratch database
  created and dropped for this round):** no-DSN
  `packages/maistro-core/tests/backlog` **96 passed / 20 skipped** (the 18
  PG-parametrized legs skip without `MAISTRO_TEST_PG_DSN`; a genuinely
  DSN-less run is the correct shape for that number — see the clarification
  appended to the fifteenth addendum of `82-backlog-work-source.md`, which
  also records the DSN-present proof **114 passed / 2 skipped** at this
  head); `alembic upgrade head` walks the full chain onto the fresh database
  ending `059 → 060`; `tests/migrations/test_migration_chain.py` **17
  passed**.

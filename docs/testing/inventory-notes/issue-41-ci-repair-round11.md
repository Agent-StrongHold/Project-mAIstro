---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 41 CI repair (round 11): ruff-format fix, develop-sync confirmation, full battery

Round scope: repair the prior verify failure
(`uv run ruff format --check .` → check-2.log: "Would reformat:
packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py"),
confirm the develop-sync block is resolved, re-run the vulture per-identity
gate and the full validation battery. No test cases added or removed; the
reformat only reflows two `store.complete(...)` call sites, so the collected
count is unchanged.

## Format fix

`test_idempotency_purge_driven.py` was the one file `ruff format --check`
rejected (2567 files were clean). `uv run ruff format` applied the canonical
layout (call fits on one line); `ruff format --check .` now reports 2568
files formatted. Semantics unchanged (assertion bodies identical).

## Develop sync

The preserved conflict was already resolved and committed (876da1f28 +
merge 32b174c47). This round fetched origin: `origin/develop` is still
`2d65104af`, already an ancestor of HEAD — no new merge required.

## Vulture per-identity gate (exact-debt-ledger round duty)

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`: exit 0, 1412 reviewed
identities -> 1412 findings, unclassified 0, never_allowlist 0. No genuinely
dead identities surfaced, so `quality/vulture-baseline.json` is unchanged
(no amendment needed).

## Environment repair: root `.env` broke subprocess-import tests

The gitignored root `.env` (present since Sep 25 08:57, documented as a
hazard in rounds 9 and 10) carries `API_KEYS=test`, which `Settings` cannot
parse for `api_keys: list[str]`. The repo-root `conftest.py` disables
dotenv loading for in-process tests, but `runs/test_import_order.py` spawns
subprocesses that re-read `.env` from CWD, so 8 of its cases failed from a
repo-root run (`import maistro.runs` itself raised SettingsError). The value
was corrected in place — `API_KEYS=["test"]`, preserving the file's intent —
which is environment repair of an untracked file, not a tree change.
Afterwards `python -c "import maistro.runs"` succeeds and the full
maistro-core suite passes from the repo root.

## Validation battery (all from head 32b174c47 + this round's reformat)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 2568 files formatted.
- `uv run pytest packages/maistro-core/tests -q` — 10391 passed, 701 skipped, 1 xfailed
  (was 10383 passed + 8 failed before the `.env` repair; the 8 were all
  `test_import_order` subprocess cases).
- `uv run pytest packages/maistro-core/tests/tasks -q` — 348 passed, 8 skipped (#1176 fencing/purge suites).
- `uv run pytest packages/maistro-core/tests/runs -q -k "admission or chat or direct"` — 126 passed, 7 skipped.
- `uv run pytest packages/maistro-server/tests -q` — 390 passed; explicitly
  chat gate + chat completions + runs API + tasks idempotency: 70 passed.
- `uv run pytest packages/hive-conductor/backend/tests -q` — 2782 passed, 6 skipped.
- `uv run pytest tests/migrations -q` — 17 passed, 83 skipped (alembic 038 task idempotency chain).
- `uv run mypy` over the six package src trees — clean (721 files).
- `check-vulture-baseline.py` — 1412 -> 1412; `check-radon-baseline.py` — 68 -> 68;
  `check-backlog-consistency.py` — ok (151 items); `check-durable-table-inventory.py` —
  ok (63 tables, now also from repo-root CWD); `check-ac-state.py` — exit 0;
  `check-m1-convergence-freeze.py --base origin/develop` — no unapproved island;
  `check-merge-markers.py` — ok; `check-suite-inventory.py` — ok (13 suites).

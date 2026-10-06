---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 41 repair (round 14): make the round-13 note parseable by the suite-inventory gate

Delta note: `+0` against the gated `packages/maistro-core/tests` suite — this
round changed documentation only; no test files were added or removed.

## What the verifier actually caught

The previous verify round (`4c6d5feafacf`) failed exactly one check:
`scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
with

```
error: docs/testing/inventory-notes/issue-41-repair-round13.md: cannot read
`packages/maistro-core/tests/tasks: +0 (existing suites re-run as evidence; no
new test files)` as `<suite>: <±count>` under `inventory-delta:`
```

Two real defects in the round-13 note's front matter, not scanner noise:

1. The delta line carried a parenthetical explanation after the integer.
   `DELTA_LINE_RE` (`scripts/check-suite-inventory.py:160`) accepts only
   `<suite>: <±count>` with nothing trailing — an unparseable block raises
   instead of silently reading as zero, by design.
2. The delta named `packages/maistro-core/tests/tasks`, a sub-suite with no
   entry in `RECIPES` — every recorded delta must name a gated suite or the
   gate refuses it. The gated identity for this tree is the parent
   `packages/maistro-core/tests`.

## Fix

`docs/testing/inventory-notes/issue-41-repair-round13.md` now records
`packages/maistro-core/tests: +0` (the same convention the other 100+ notes
use) with the explanation moved into prose. No gate code was touched.

## Validation executed

- `uv run python scripts/check-suite-inventory.py` → `ok` for all 14 suites,
  including `packages/hive-conductor/backend/tests` (the exact failing check).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; 1403 reviewed
  identities → 1403 findings, no unbanked debt (CI gate repair round
  re-confirmed; no ledger amendment needed).
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .`
  → 2584 files already formatted.
- `uv run pytest packages/maistro-core/tests/runs/test_parked_run_resume.py
  packages/maistro-core/tests/runs/test_spine_conformance.py
  packages/maistro-core/tests/tasks/test_idempotency.py
  packages/maistro-core/tests/tasks/test_idempotency_durable.py
  packages/maistro-core/tests/tasks/test_idempotency_purge_driven.py
  packages/maistro-server/tests/api/test_tasks_idempotency.py -q` →
  407 passed, 126 skipped.
- `.venv/bin/python -m pytest packages/hive-conductor/backend/tests/
  test_engine_service.py -q` (bare python per the documented trap) →
  35 passed.

## Acceptance-criteria spot-check against production code (issue #41)

- Task admission mints a canonical Run and returns its `run_id`
  (`packages/maistro-core/src/maistro/tasks/admission.py:97,190-253`, one
  committed QUEUED Run per logical submission).
- Chat turns admit through the same seam over the trivial one-node Graph
  (`packages/maistro-core/src/maistro/runs/chat_admission.py:282`), and
  single-node Runs execute as Attempts under their NodeRun
  (`packages/maistro-core/src/maistro/runs/consumption.py`).
- Durable scoped idempotency precedes Run minting
  (`packages/maistro-core/src/maistro/tasks/idempotency.py`; migration
  `alembic/versions/038_task_idempotency.py`; ambiguous-admission discovery
  via `run_for_task_receipt` → `RunStore.find_run_by_task_receipt`).
- The Run is the authoritative post-admission state: the QUEUED→RUNNING
  dispatch write is the physical fence
  (`tasks/admission.py:313-329`); admission/queue/session records stay
  receipts.
- Session/request provenance travels in the Run
  (`runs/chat_admission.py:65-66,276-277`).

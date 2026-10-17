---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 CI-repair round at 5f23a3128 (job 23f03912)

Snapshot: issue #1893 only; branch `auto-1893`, starting HEAD verified exactly
`5f23a3128056b816de6acc32d52c3f42f9b34356`, worktree clean, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7` re-fetched and re-confirmed as
`origin/develop` (no new upstream commits; merge-base equals the develop tip).
No GitHub mutations, no ledger/grant edits, no source or test edits this round.

## Fresh evidence executed this round (all commands run at this head)

- `uv run ruff check .` -> PASS; `uv run ruff format --check .` -> PASS
  (3277 files already formatted).
- `uv sync --locked --all-extras` then `uv run mypy --strict
  packages/maistro-core/src` -> PASS (784 files, exit 0). Note: with only
  `--extra dev` installed, mypy reports 5 pre-existing `import-not-found`
  errors for `maistro_bootstrap.*` in `cli/_install.py`/`cli/_builders_tui.py`
  (files this branch never touched); CI's `--all-extras` environment resolves
  them. exact-debt-ledger's environment is `--all-extras`.
- Vulture, CI-exact argv: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` -> PASS
  (1323 reviewed identities -> 1323 findings, exit 0). No unbanked debt; the
  CI-repair-round permission to amend `quality/vulture-baseline.json` has
  nothing to act on, and nothing was amended.
- Candidate gates: `check-reachability.py` PASS (1396 modules, 171
  unreachable, all dispositioned); `check-reachability-dispositions.py` PASS
  (50 groups: 149 CONNECT, 20 LIBRARY, 2 RETIRE);
  `check-shipped-surface-truth.py` PASS;
  `check-promotion-surface.py` PASS (74 tolerated);
  `check-suite-inventory.py --suite packages/maistro-core/tests` PASS
  (16466 node IDs, delta 0).
- Focused pytest, no PG:
  `packages/maistro-core/tests/runs/test_root_admission_identity.py` +
  `packages/maistro-core/tests/tasks/test_admission_codec.py` -> 201 passed,
  3 skipped (the PG legs).
- Durable PG leg, independently reproduced: created disposable database
  `maistro_1893_23f03912` on the pgvector/pg18 (PostgreSQL 18.6) instance at
  127.0.0.1:5433 after confirming the name was absent; `uv run alembic upgrade
  head` migrated the real chain 001->062 (68 upgrades, exit 0); reran the two
  focused files with `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`
  both targeting that database and `MAISTRO_REQUIRE_PG_LEGS=1` -> **204
  passed, 0 skipped**. Post-run residue counts measured by direct SQL:
  `task_idempotency` total 0 (0 format_version=1, 0 format_version=2),
  `canonical_runs` 0.
- CI `test` job selection, CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
  RATCHET_BASE_REV=origin/develop`): `uv run pytest tests/
  --ignore=tests/tools/registry -q` -> **4971 passed, 129 skipped, exit 0**
  (4m49s); `uv run pytest packages/maistro-server/tests
  packages/maistro-turing/tests packages/maistro-turing/backend/tests
  packages/maistro-design/tests packages/maistro-ext-harness/tests
  packages/maistro-ext-sdk/tests -q` -> **1849 passed, 9 skipped, exit 0**.
- Adjacent suites: `packages/maistro-core/tests/tasks` +
  `packages/maistro-core/tests/runs` -> 1918 passed, 310 skipped
  (backend-inapplicable legs), exit 0.
- Trusted-base provenance, CI-shaped: `RATCHET_BASE_REV=origin/develop uv run
  python scripts/check-ratchet-provenance.py` -> FAIL (exit 1), exactly:
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are
  NEW unreachable modules absent from the trusted base, and their two NEW
  dispositions are absent from the trusted ledger; every other ratchet in the
  battery (adr-status-language, citation-status, promotion-surface,
  shell-execution, contract-markers, enumerations, lifecycle) is OK.

## The reported `test: failure` is not this head's failure

The supplied dispatch snapshot contains exactly one failing `test` check-run,
at head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` started 2026-10-03 — the
head of PR #1855 (issue #1572's PR), not this branch. At this branch's PR
#1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` (captured 2026-10-11),
`test` is SUCCESS and the only failing check is `exact-debt-ledger`. Both
halves of the `test` job that CI runs on Python pass at this head locally with
CI's environment (counts above). No repair target for `test` exists on this
branch; the #1855 failure belongs to that lane.

## The one red gate is structurally blocked on the two-merge rule

`scripts/ratchet_provenance.py::load_authorizations` reads grants **from the
base revision** ("a new grant does not take effect in the change that
introduces it. Authorizing a floor-raise is now two merges -- the grant, then
the regression it permits"), and `check-reachability-provenance.py` resolves
the trusted base as the merge-base with `origin/develop` = `3c761d14`, which
contains no reachability grant for the two modules. In-branch alternatives are
all prohibited: wiring the modules to make them reachable violates B2's
"typed representation only / no live _assess change" scope; editing the gate or
self-authorizing violates the issue's "no baseline/grant/gate modifications to
make an unwired slice green" and the two-merge mechanism itself. The vulture
side of the same CI job is green via the established `_vulture_whitelist.py`
scanner-input mechanism (references only, module never executes, ships in no
wheel). Resolution remains upstream: land the reachability authorization for
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec` on
develop, then merge develop into `auto-1893`.

## Scope hygiene re-verified

`git diff origin/develop...HEAD` production surface is exactly:
`packages/maistro-core/src/maistro/tasks/admission_codec.py` (new),
`packages/maistro-core/src/maistro/runs/admission_identity.py` (new, #1851
prerequisite), `packages/maistro-core/src/_vulture_whitelist.py` (+32
reference lines), the two test files, `quality/reachability-baseline.json`
(+2 rows), `quality/reachability-dispositions.json` (+1 group), and docs.
No SQL mutation, HTTP mapping or queue change exists anywhere in the diff;
the only production importer of either module is `_vulture_whitelist.py`
(scanner input). Commit messages reference `(#1893)`; no closure keyword.

Verdict of this round: all B2 functional acceptance criteria hold at this
head under fresh execution; the remaining red is the upstream two-merge
sequencing only.

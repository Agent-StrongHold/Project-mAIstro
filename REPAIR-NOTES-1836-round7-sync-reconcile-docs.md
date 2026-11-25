# Repair #1836 round 7 — develop-sync reconcile + docs salvage commit (branch auto-1836, head 075507faa)

Starting point: assigned head `e9c9d1fa0` with three uncommitted docs files
(salvage from the previous round, which died on provider error 410
ModelDeprecated before producing check-*.log files — the job directory
`/home/dev/maistro/jobs/43a7052255d842909a0cc0134ec9c1e2` contains none).

## What the driver/actuator had already done remotely

- `origin/auto-1836` head became `d82c1aab` = merge of develop `41deb105`
  into `e9c9d1fa0`, pushed 2026-10-26T09:49Z by the Cursor Agent actuator.
  It already contained, byte-identical, two of the three salvaged docs files
  (`docs/ci/BRANCH-PROTECTION.md`, `docs/ci/REQUIRED-CHECKS.md` — CodeQL
  `Analyze (actions/js-ts/python)` rows now `adv` on develop / required on
  main, matching the live workflow after #2357/#2359).
- All CI runs at `e9c9d1fa0` were **cancelled** (superseded by that push),
  which is exactly the reported merge-queue failure
  "commit status not successful": required statuses never completed, no
  in-tree defect at that head.

## What this round did

1. Committed the salvage: `a6a84c033` — the two docs files (now matching the
   remote merge) plus `CHANGELOG.md`: the "CodeQL workflow scope test expects
   `develop` triggers" entry is attributed to **#2359** (merged 2026-10-26,
   "pin CodeQL scope test to develop triggers (#2357 follow-up)", introduced
   the entry at `73c065f52`) instead of the remote's bare "(#2357)"; #2357's
   work is the separate Security entry. Verified against `gh pr view 2359`
   and `git log -S`.
2. Merged `origin/auto-1836` (`d82c1aab`) → merge commit `075507faa`, the
   only conflict being the CHANGELOG attribution line, resolved to the
   accurate `(#2359, follow-up to #2357)`. Tree delta vs the CI-running
   remote head `d82c1aab`: exactly 1 CHANGELOG line, no code, no workflow,
   no ledger input to any gate.

## Local validation at `075507faa` (CI-exact invocations)

- `uv run python scripts/check-workflow-inventory.py` → rc 0, clean (32
  workflows dispositioned); the devskim row still carries
  `workflow_dispatch` (repair `0ec6d9481` survived the develop sync).
- `uv run ruff check .` → rc 0; `uv run ruff format --check .` → rc 0
  (3536 files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → rc 0, 1255 reviewed
  identities == 1255 findings, base `41deb105ca60` (the develop-sync +1
  vulture row is accounted for; no unbanked identity).
- `uv run python scripts/check-branch-protection.py` → rc 0 ("19 on develop,
  33 on main; every PR check is required or explicitly advisory") — this is
  the gate that cross-checks the two docs files edited this round.
- `uv run python scripts/check-suite-inventory.py` → rc 0, 21 suites match.
- `uv run pytest tests/test_codeql_scan_scope.py
  tests/test_check_pyright_report.py
  packages/maistro-core/tests/agents/test_factory_prompts_diff_connect.py`
  → 73 passed (the CodeQL pin, the develop-sync pyright fixture change, and
  the develop-sync factory feature test).
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  41deb105ca60a38720a1354f653e392ad9f6a482` → rc 0: design_coverage
  39.6633 ≥ authorized floor 39.641, acceptance mandate 0 unproven, chain
  mandate clean, 10 debt counters on ceilings folded from 47 notes at the
  new develop base.
- `uv run mypy <canonical 7 src dirs>` → rc 0, 944 source files.
- `uv run python scripts/check-release-consistency.py` → rc 0 (reads the
  edited CHANGELOG entry shape); `scripts/bump_version.py --check` → rc 0
  (42 sites, 0.9.0); `git diff --check` → clean.

## Remote CI evidence at `d82c1aab` (tree == this head minus 1 docs line)

Completed **success**: DevSkim (run 40302499151 — the previously red
commit-status check), CodeQL Advanced (40302499140 — Analyze jobs), Vulture
Ratchet (40302499133), Formal Conformance (40302499051), Gate C
(40302498903), Cage Guard (40302498970), Registry CI (40302499015).
Still **queued** at round end: quality (40302499005), CI (40302499095),
security (40302499200) — runner backlog, not failures. Integration Scope
run 40302499131 was infra-cancelled at 10:56Z with no newer run superseding
it (last success on this branch: `a7839ecfc`, run 40263007043, same branch
shape); not reproducible from the tree.

No test was added, moved, or removed this round → no suite-inventory delta
note required. No quality/ ledger change authored by this round (the +1
vulture / +1+10 reachability rows came from develop `41deb105` via the
sync, and the vulture gate is green against base `41deb105`).

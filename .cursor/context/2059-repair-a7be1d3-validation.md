# #2059 repair round — exact-head validation log (2026-11-25, round 2)

Lane CR2059, job `18f65fad19c843e9a743e4b07ac5125d`.
Head: `a7be1d3a954858a5e081718ec0bc3e798dc453b6` (= PR #2059 head; includes
`fab8d98224` merge of develop `80c837d578` + the x/net ARG-floor guard
repair). Supersedes `.cursor/context/2059-repair-cec70da-validation.md` for
everything after that head. **No production code changed this round** — every
gate below was re-proven independently rather than inherited, per the brief
("do not assume earlier verification claims are true").

## Block resolution: develop sync

The brief carried "develop sync conflict preserved in worktree; resolve before
verification". Fetched `origin`: tip of `origin/develop` is exactly
`80c837d578c6a866f3d8114edb72dbca3def4d6e` — identical to the lane's declared
base. `git merge-base HEAD origin/develop` = same commit; `git rev-list
--left-right --count HEAD...origin/develop` = `39 0` (ahead 39, **behind 0**).
The merge commit `fab8d98224` ("Merge origin/develop (80c837d578, #2110 …)")
is already in history and `git status` is clean with no MERGE_HEAD. The sync
was already completed by a prior round; nothing to resolve.

## CI-repair instruction: exact-debt-ledger — executed, no-op

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (byte-identical to the
`quality.yml` and `vulture-ratchet.yml` invocations): **exit 0**, total
findings 1221 across 10 classified buckets, `unclassified: 0`,
`never_allowlist: 0`, baseline base `80c837d578c6`, candidate
`a7be1d3a9548`, `1221 reviewed identities -> 1221 findings`. **No unbanked
identities exist at this head, so no ledger amendment was required** — the
permitted exception stays unused, `quality/vulture-baseline.json` untouched.

## Independent reproduction of Quality / Acceptance state (full CI shape)

The prior verify round claimed the gate passes only in full CI shape; this
round reproduced it from scratch rather than trusting that claim:

- `uv sync --locked --all-extras` (460 pkgs; note it **uninstalls**
  maistro-evolve, matching CI which re-adds it next)
- `uv pip install -e packages/maistro-evolve`; `uv pip install pytest-timeout`
- pgvector `pgvector/pgvector:pg18` container (same image as CI's
  quality-acceptance service) on `127.0.0.1:5434`, credentials `maistro:maistro`
  db `maistro_test` (identical to the workflow's env); `MAISTRO_TEST_PG_DSN` +
  `DATABASE_URL` pointed at it
- `uv run alembic upgrade head` → exit 0
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  80c837d578c6a866f3d8114edb72dbca3def4d6e` (CI's exact PR invocation shape,
  MANDATE_BASE_SHA = PR base sha) → **exit 0**: design coverage **44.4608%**
  exactly on the banked floor, all 10 debt counters exactly on ceilings,
  criteria mandate OK (0 added/unproven), chain mandate OK (0 absent links).

This closes the "floor only reproducible in CI-shape env" finding with fresh
evidence: deterministic, not a high-water artifact.

## Local replays at the exact head

- `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .`
  → "3659 files already formatted"
- `uv run pytest tests/test_ci_vulture_ownership.py
  tests/test_gates_ran_merge_group_scope.py tests/test_check_gates_ran.py
  tests/test_check_required_checks.py -q` → **232 passed**
- `uv run pytest tests/test_devskim_scan_scope.py
  tests/test_distribution_contract.py
  tests/test_docker_cli_vendored_advisory_floors.py
  tests/test_cpython_base_grype_floor.py
  tests/test_temporalio_bridge_zip_floor.py
  tests/test_restore_oracle_characterization.py
  tests/test_restore_oracle_readiness_gate.py -q` → **66 passed**
- `scripts/check-required-checks.py` → ok, 79 PR checks match REQUIRED-CHECKS.md
- `scripts/check-backlog-consistency.py` → OK, 167 items
- `scripts/check-ratchet-provenance.py` → OK, all ten sub-ratchets
  (adr-status-language, citation-status, promotion-surface,
  reachability-dispositions, reachability, shell-execution, contract-markers,
  enumerations, lifecycle, vulture provenance) no candidate-approved expansion
- `scripts/check-shipped-surface-truth.py` → matrix complete
- `scripts/check-suite-inventory.py` → ok, 21 suites match recorded inventory
  (delta 0; no test files changed this round, so no inventory-note delta)

## Residual (outside worker mutation scope)

1. **PR body stale figure**: body claims "1,328 reviewed identities"; the
   exact-head scan (above) measures **1221 = 1221**. Refresh body numbers
   before merge — a GitHub-side edit, not a tree change.
2. **Hosted checks**: every statusCheckRollup entry on head `a7be1d3a9548` was
   QUEUED at dispatch capture time. Hosted split-profile CI on the exact head
   remains required before merge; local reproduction cannot substitute for it.
3. Draft/hosted-state drift in the PR body ("keep draft pending…") likewise
   GitHub-side.

No test files were added or changed this round → no inventory delta required.
Tree left clean at `a7be1d3a9548…` plus this note.

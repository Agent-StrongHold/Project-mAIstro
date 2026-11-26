# #2059 repair round — exact-head validation log (2026-11-25)

Lane CR2059, job `7f2c499f3c7143df979869acf3bc0d57`.
Head: `cec70dab8c609a352f21bf56b1e78cd625761f2a` (= PR #2059 head; =
`4ee57043ac` merge of develop `221dc3d517` + gates-ran reconciliation
`cec70dab8c`). Lane base: `d5eea943294b89caab6a3cafacebe6f3a60c0a60`.
Supersedes `.cursor/context/2059-repair-4f5408b8-validation.md` for everything
after that head. No production code changed between `4f5408b8e4` and this
head beyond the develop merges and the gates-ran path-filter reconciliation,
but every RED-list gate was re-proven here rather than inherited, because the
previous block flagged that a worker had made **no commit** — a clean tree is
not proof of repair.

## Why this round exists

1. The lane brief repeated "CI response truncated; manual inspection required".
   Manual inspection of the check-runs capture at `cec70dab8c` (dispatch
   `sources/repos/.../commits/cec70dab8c.../check-runs`, captured
   2026-11-25T10:42Z): **131 check runs, every one `success`** except one
   `Container scan + SBOM + cosign` = `skipped` (expected on that event
   shape). The stale "RED gates" list in the brief predates these runs;
   nothing is red at the exact head.
2. The prior finding that `design_coverage 44.4608` was a "non-reproducible
   high-water mark" (three local FAILs) was re-examined: those replays used a
   wrong-shaped database (host pg on :5433 with db `maistro`, or no DB, or no
   `maistro-evolve`). The CI shape is db **`maistro_test`** on :5432
   (`quality.yml` quality-acceptance service env). Re-run in the exact shape:
   **exit 0, measured 44.4608%, twice** — deterministic, the bank is honest.
3. The vulture CI-repair instruction (exact-debt-ledger amendment) was
   executed and is a **no-op**: no unbanked identities at head.

## Local replays at the exact head (CI-exact or CI-shaped)

Environment: `uv sync --locked --all-extras`, `uv pip install -e
packages/maistro-evolve`, `uv pip install pytest-timeout vulture` (vulture
2.16), age/age-keygen present; PostgreSQL 18.6 (host systemd, same major as
CI's `pgvector/pgvector:pg18`) at `127.0.0.1:5432/maistro_test`;
`MAISTRO_TEST_PG_DSN` and `DATABASE_URL` set to
`postgresql://maistro:maistro@127.0.0.1:5432/maistro_test`;
`uv run alembic upgrade head` at head (no-op, exit 0).

| Gate | Invocation | Result |
|---|---|---|
| exact-debt-ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **exit 0 — 1221 reviewed identities -> 1221 findings**, base `221dc3d517e7`, candidate `cec70dab8c60`, unclassified 0, never_allowlist 0. No unbanked identities; the instructed ledger amendment is a no-op, none made |
| Acceptance state (PR shape) | `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate d5eea943294b89caab6a3cafacebe6f3a60c0a60` | **exit 0, twice** — design_coverage **44.4608% over 166 taken decisions (87 at zero)**, exactly on the floor, deterministic across runs; 10 debt counters on ceilings folded from 50 notes at `221dc3d517e7`; criteria mandate 0 added/unproven; chain mandate clean |
| Backlog consistency | `uv run python scripts/check-backlog-consistency.py` | exit 0 |
| Contract markers | `uv run python scripts/check-contract-markers.py` | exit 0 |
| Convergence matrix | `uv run python scripts/check-convergence-matrix.py` | exit 0 |
| Agent store writes | `uv run python scripts/check-agent-store-writes.py` | exit 0 |
| BFCL provenance | `uv run python scripts/vendor_bfcl.py --check` | exit 0 |
| Architecture fitness | `uv run pytest packages/maistro-core/tests/fitness -q --timeout=30` | **39 passed** |
| Branch tests (vulture ownership) | `uv run pytest tests/test_ci_vulture_ownership.py tests/test_check_gates_ran.py tests/test_check_required_checks.py tests/test_gates_ran_merge_group_scope.py tests/test_devskim_scan_scope.py -q` | **254 passed** |
| Branch tests (floors/contract/oracle) | `uv run pytest tests/test_distribution_contract.py tests/test_cpython_base_grype_floor.py tests/test_docker_cli_vendored_advisory_floors.py tests/test_temporalio_bridge_zip_floor.py tests/test_restore_oracle_characterization.py tests/test_restore_oracle_readiness_gate.py -q` | **44 passed** |
| Ruff | `uv run ruff check .` / `uv run ruff format --check .` | clean / 3659 files formatted |
| Suite inventory | `uv run python scripts/check-suite-inventory.py` | ok — 21 suite(s) match |

## Floor provenance for the disputed bank

`git grep -l "44.4608" 221dc3d517 -- quality/ac-state-notes/` →
`quality/ac-state-notes/auto-62.json`: the enforced floor already exists at
the merge-base revision. The ratchet's fold list (printed by the gate) does
**not** include this branch's own
`quality/ac-state-notes/fix-vulture-single-owner-1357.json`, so the floor is
not self-authorized by the candidate — the branch note is documentation of an
already-authorized floor, not its source.

## Not locally reproducible; hosted evidence cited

Coverage gate (publish-set floor + diff coverage) is a 45-minute job that
combines coverage artifacts downloaded from three producer jobs
(coverage PostgreSQL / MinIO / no-services); it cannot be meaningfully
replayed on one machine. At `cec70dab8c` hosted CI shows it `success` in both
the PR and merge-group evaluations (check-runs capture cited above).

## Stale GitHub-text findings (evidence only, no code defect)

- Issue body "1,328 reviewed identities" — actual gate output at head is
  **1221 identities -> 1221 findings** (gate passes; body text predates later
  ledger shrinks on develop merges).
- Issue body "The sole semantic workflow change is this step condition" — the
  branch additionally bumps pinned CPython base images 3.13.16→3.13.18
  (commit `464752a820`) and Dockerfile bases, with their own inventory notes
  and floor tests.
- Issue body "root suite inventory matches 5,066 cases" — current gate reports
  "21 suite(s) match"; the absolute count is not restated here.
- Issue body says "Keep draft pending exact-head hosted checks" while the PR
  snapshot shows `draft: false`; draft state is a GitHub-side field, not a
  repo artifact.

## Round outcome

No production defect found; every gate re-proven at the exact head. This note
is the round's committed artifact, per the writer rule.

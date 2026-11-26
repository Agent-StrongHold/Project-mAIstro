# repair-2110 @ c7d10dc — round-3 verification evidence

Round-3 verification of `fix/windows-bootstrap-prerequisite` at merged head
`c7d10dc766` (branch `db0da81d84` + develop `d0e8e235`, the #2120 node:26 sync).
Five prior repair jobs died on provider errors before doing any work; this round
re-proves everything executable locally and adjudicates the stale findings.

## CI state (evidence, not assumption)

- Dispatch context check-runs for `db0da81d84`: **126/126 completed, all
  `success`** except one duplicate `Container scan + SBOM + cosign` entry marked
  `skipped` (cancelled re-run). Every gate RED in the older attempt history is
  green there: Compliance registry, Container scan + SBOM + cosign, Coverage
  gate (publish-set floor + diff coverage), Gate C — canonical clean install,
  Quality / Acceptance state, Quality / Agent store writes, Quality /
  Architecture fitness, Quality / BFCL provenance, exact-debt-ledger.
- Round-1 findings "design_coverage 40.3661 < floor 44.4608 at head" stay
  refuted (round-2 note `repair-2110-d2dfeb95-gatesran.md`): base f8a2df96
  measures 39.8641 in the identical service-less env; CI's DB-backed env passes,
  confirmed by the green `Quality / Acceptance state` check-run.
- GitHub reported PR #2110 `mergeable_state: dirty` at head `db0da81d84`
  because develop moved to `d0e8e235` (image-pins provenance conflict). The
  local merge `c7d10dc` resolves it: `git fetch` confirms `origin/develop` is
  still exactly `d0e8e235`, and `uv run python scripts/check-image-pins.py`
  exits 0 at the merged head (9 pins, 10 Dockerfiles, all registered). No
  quality-ledger rows lost across the merge (`git diff --numstat` vs both
  parents; only the branch's ac-state note and develop's 9 image-pin rows move).

## Local re-validation at c7d10dc (all executed this round)

- `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → **28 passed** under
  pwsh 7.4.6 (harness test ran for real, not skipped).
- `pwsh -NoProfile -NonInteractive -File tests/installer/run-wsl-detection-e2e.ps1`
  → 23 WSL-detection cases + relaunch-policy harness all passed.
- Negative proof: harness run against base `d0e8e235`'s get.ps1 fails with
  "Unexpected elevation arguments" — the regression test detects the old code.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1236 reviewed
  identities banked, no drift across the develop sync.
- `uv run python scripts/check-suite-inventory.py` → ok: 21 suites match;
  `docs/testing/inventory-notes/security-windows-policy-prerequisite.md`
  (`inventory-delta: tests/: +3`) remains accurate.
- `uv lock --check` → ok. Worktree clean before/after this note.

## Suppression audit (adversarial re-check)

`.gitleaksignore` fb322ab rows: `test_attribution.py:462,476` are the Python
name `context_key` beside `kind=ProducerKind.MUTATION_OPERATOR`;
`test_task_admission_generation_upgrade.py:46` is `GENERATION_ID`, a synthetic
32-hex CHECK-contract fixture. No credential suppressed. Gitleaks gate green at
db0da81d84.

## Residual limits (unchanged, documented)

Real Windows script-policy enforcement, UAC, RunOnce resume, and reboot were not
exercised locally (no Windows host); PowerShell 5.1 untested locally (only pwsh
7.4.6). CI at the pushed merge head must re-run — this lane cannot push.

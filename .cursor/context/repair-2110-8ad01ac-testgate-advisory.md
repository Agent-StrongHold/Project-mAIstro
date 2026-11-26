# repair-2110 @ 8ad01ac — round-4 evidence: the single red gate is branch-neutral

Round-4 verification at head `8ad01ac0c2` (= `c7d10dc766` + docs-only
commit). Round-3 left CI green at `db0da81d84`; this round adjudicates the
fresh check-runs captured at the new head by the driver
(dispatch-context.json, captured 2026-11-18T02:14Z).

## CI state at 8ad01ac0c2 (from dispatch check-runs data)

- 126 check-runs: **125 success + 1 skipped + 1 failure**. Every gate RED in
  the attempt history is success at this head: Compliance registry,
  Container scan + SBOM + cosign, Coverage gate (publish-set floor + diff
  coverage), Gate C — canonical clean install, Quality / Acceptance state,
  Quality / Agent store writes, Quality / Architecture fitness, Quality /
  BFCL provenance, exact-debt-ledger.
- The only failure is the `test` job (run 44214617236, job 134501217717),
  failing at step `npm audit --audit-level=high` in
  `packages/maistro-canvas/frontend` (.github/workflows/ci.yml:703):
  **GHSA-fc5q-39xc-vjpf / CVE-2026-112366** (picomatch ReDoS, HIGH),
  transitively via vitest→tinyglobby→fdir and vite ≥6.3.0-beta.0.

## Why that failure is not this branch's (controlled experiment)

- Branch diff vs base `d0e8e235` under `packages/maistro-canvas`: **empty**
  (`git diff --stat d0e8e235..HEAD -- packages/maistro-canvas` prints
  nothing). Base `d0e8e235` **is** `origin/develop`'s head right now.
- `test` **passed** at base `d0e8e235` (job 133967393584, finished
  2026-11-17T10:50Z) and **failed** at this head (finished
  2026-11-18T01:33Z) with a byte-identical frontend tree; the only thing
  that changed in between is the advisory database: OSV records
  GHSA-fc5q-39xc-vjpf `modified: 2026-11-17T16:00:03Z`.
- The advisory has **no fixed version** (affected range `introduced: 0`,
  `last_affected: 4.0.7`; npm itself reports the only "fix" is a breaking
  vitest reinstall). No pin/override on this branch can clear
  `npm audit`; muting the audit step would weaken a gate, which this lane
  must not do. The fix belongs to a dependency-repair lane once picomatch
  ships a patched release.

## Local re-validation at 8ad01ac0c2 (all executed this round)

- `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → **28 passed**
  (pwsh 7.4.6 present; harness test executed, not skipped).
- Selected: the 3 new tests `test_download_example_requires_approved_execution_policy`,
  `test_relaunch_functions_do_not_override_execution_policy`,
  `test_relaunch_argument_construction` → all PASSED.
- `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1` →
  23 WSL-detection cases + `RESULT relaunch-policy ok`, exit 0.
- Negative proof: harness against base `d0e8e235`'s get.ps1 throws
  "Unexpected elevation arguments", exit 1 — the new regression detects
  the old `-ExecutionPolicy Bypass` code.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 3572
  files already formatted.
- `uv run python scripts/check-suite-inventory.py` → ok: 21 suites match
  (`inventory-delta: tests/: +3` still accurate; no tests changed this
  round, so no new inventory note is required).
- `uv run python scripts/check-test-duplicates.py` → ok, 0 groups.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1236 banked.
- PR body (dispatch data) contains no fixes/closes/resolves keywords.

## Residual limits (unchanged)

Real Windows script-policy enforcement, UAC, RunOnce resume, and reboot
remain unexercised locally (no Windows host; PowerShell 5.1 untested — only
pwsh 7.4.6). The `test` job stays red repo-wide until picomatch publishes a
patched release or the audit floor is moved deliberately in a dependency
lane; this branch does not touch that dependency tree.

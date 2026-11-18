---
inventory-delta:
  added: 0
  removed: 0
  modified: 0
---

# cr-2371 — grant-only PR verification (#1629 debt authorization)

No test inventory change (no tests added, removed, or modified). This PR is a
two-merge ratchet grant only: one entry `@tool/plan_delivery` under
`reachability` in `quality/ratchet-authorizations.json` (+5 lines vs merge-base
`78133c093e0a`), so #1640 can bank the matching baseline/disposition row from a
base that already carries the grant.

## Evidence (local, CI-exact arguments)

- Merge-base diff `78133c093e..272fd3aade` touches exactly one file:
  `quality/ratchet-authorizations.json` +5. No product code, no baseline or
  disposition edits.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  (the exact-debt-ledger job's invocation, vulture-ratchet.yml) → exit 0;
  resolves base `78133c093e0a`, candidate `272fd3aade`, "no candidate-approved
  expansion", "55 quality JSON consumer(s) have explicit provenance".
- `uv run python scripts/check-reachability.py` (quality.yml Quality /
  Reachability) → exit 0; 102 unreachable of 1477, unchanged.
- `uv run python scripts/check-reachability-dispositions.py` (quality.yml
  Quality / Reachability dispositions) → exit 0; 35 groups cover 102 modules.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI args) → exit 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- `uv run python scripts/check-compliance.py` → exit 0.
- `uv run pytest tests/test_ratchet_provenance.py
  tests/test_check_ratchet_provenance.py tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py tests/test_check_reachability_dispositions.py`
  → 133 passed.
- Driver battery: `uv sync --locked` ok, `ruff check` all passed, `ruff format
  --check` 3537 files formatted.

## Why the RED CI picture is not a content failure

Every check run on head `272fd3aade` was cancelled twice (mass cancellation at
2026-10-26T11:07:32–39Z of all jobs started 11:00:34, second wave cancelled
~11:17–11:18Z; PR timeline shows only auto-merge enable/disable around those
times). The three `failure` conclusions are aggregate/waiter jobs reporting
cancelled dependencies, not scanner findings:

- "Quality gate (Pillars 1–4, 7, 8)": every matrix dep "dependency did not
  succeed".
- "SAST (bandit + semgrep + gitleaks)": sast-bandit/sast-semgrep "dependency
  did not succeed".
- "integration-scope": "docker-build is required by integration scope but
  concluded cancelled".

No gate that inspects this file ever ran against the content on GitHub; every
such gate passes locally with CI's exact arguments above.

## Residuals (recorded, not repaired here)

- #1640's current head places the planner at `tools/plan_delivery.py`, while
  `scripts/check-reachability.py` collects tooling from `TOOLING_DIR = "scripts"`
  only — so `@tool/plan_delivery` may never enter the baseline and the grant
  may go unexercised. Unused authorizations are harmless (the provenance gate
  passes with this grant present and unused). The grant reason's reference to
  the LIBRARY disposition describes the state #1640 is expected to bank, not a
  row that exists today.
- Branch is `mergeable_state: behind` develop (`ba7d378e`); `quality/ratchet-authorizations.json`
  is byte-identical between the branch point and current develop, so the update
  is conflict-free, and current develop does not already carry the grant.

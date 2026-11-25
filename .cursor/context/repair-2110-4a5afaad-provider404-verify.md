# repair-2110 @ 4a5afaad12ec — round: re-verification after provider-404 abort; all executable gates re-proven from scratch

Job `56f38f35896b433490097749988c222f` (repair phase). The immediately prior job
`6328bf3a3f77458ab4fe14b871ef7c72` aborted on a provider 404 after only
`uv sync` + `ruff check` + `ruff format --check` (driver result.json: all
returncode 0, `failure_kind: provider_error`) — no tree changes, nothing to
salvage (`git status` clean at 4a5afaad12ec). This round therefore re-proved
round-4's claims adversarially, from scratch, rather than trusting them.

## Hosted CI at the exact head (dispatch-context.json, captured 2026-11-18T06:01:36Z)

- `commits/4a5afaad…/check-runs`: **126 check-runs — 124 success, 1 skipped
  (Container scan + SBOM + cosign matrix leg), 1 failure (`test`)**.
  Every gate RED in the stale attempt history is success at this head:
  Compliance registry, Container scan + SBOM + cosign, Coverage gate
  (publish-set floor + diff coverage), Gate C — canonical clean install,
  Quality / Acceptance state, Quality / Agent store writes, Quality /
  Architecture fitness, Quality / BFCL provenance, exact-debt-ledger,
  SAST, Supply chain (pip-audit).
- `pulls/2110`: head `4a5afaad12ec…` == local HEAD; base `d0e8e235a896…`
  (`develop`) == `origin/develop`; open, not draft, `mergeable: true`,
  `mergeable_state: blocked` (blocked solely by the required `test` check).
- Reviews: 1 review, state COMMENTED — no CHANGES_REQUESTED.
- Latest 4 issue comments (through 2026-11-18T05:39Z): automated
  maistro-progress attempt markers only; no reviewer asks, no new criteria.

## The sole red gate, re-root-caused from scratch (not inherited from round 4)

- `git diff --stat d0e8e235..HEAD -- packages/maistro-canvas` → **empty**
  (frontend tree, including package-lock, byte-identical to base), and
  `d0e8e235` IS `origin/develop`'s head.
- CI `test` job failed at step `npm audit --audit-level=high`
  (ci.yml:703, working-directory packages/maistro-canvas/frontend).
- Reproduced locally at this head: `npm audit --audit-level=high` → exit 1,
  **picomatch `*` ReDoS HIGH (GHSA-fc5q-39xc-vjpf)** via fdir→tinyglobby←
  vitest and vite ≥6.3.0-beta.0 (6 high). npm's only offered fix is
  `npm audit fix --force` → vite@6.2.7, a **breaking downgrade**; no
  patched picomatch release exists to pin. Muting the audit step would
  weaken a required gate — not permitted for this lane. The repair belongs
  to a dependency-repair lane once picomatch ships a fix. Branch-neutral by
  tree identity: base would fail identically under the current advisory DB.

## Acceptance criteria of the PR body — executed evidence this round

1. Admin-approved prerequisite docs + read-only inspection + fail-closed
   guidance: get.ps1 `.NOTES` ("Inspect the policies read-only with
   `Get-ExecutionPolicy -List`… Do not work around the restriction").
   Only `Get-ExecutionPolicy` (read-only) references remain in get.ps1 —
   `grep -n ExecutionPolicy get.ps1` hits help text only (lines 71, 82).
2. `-ExecutionPolicy Bypass` removed from `Invoke-Elevated` (get.ps1:395)
   and `Register-Resume` (get.ps1:408); quoting, passthrough, RunOnce
   registry destination unchanged (verified in `git diff d0e8e235..HEAD --
   get.ps1` — only the policy tokens changed).
3. Post-logon resume explanation: `.NOTES` states "Resume requires an
   approved policy that remains effective after logon; a session-only
   permission is not sufficient."
4. `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → **28 passed**
   (pwsh 7.4.6); the three new regressions
   `test_download_example_requires_approved_execution_policy`,
   `test_relaunch_functions_do_not_override_execution_policy`,
   `test_relaunch_argument_construction` → all PASSED individually.
5. Harness positive + negative: `pwsh -NoProfile -File
   tests/installer/relaunch_policy_harness.ps1 -GetPs1 get.ps1` →
   `RESULT relaunch-policy ok` exit 0; same harness against
   `git show d0e8e235:get.ps1` → **'Unexpected elevation arguments'
   exit 1** (relaunch_policy_harness.ps1:42) — the regression bites the old
   code for the right reason.
6. `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1` →
   23 WSL-detection cases passed + `RESULT relaunch-policy ok`, exit 0
   (harness wired at run-wsl-detection-e2e.ps1:56).

## Named historical-RED gates re-run locally, CI-exact (all this round)

- `uv run ruff check .` / `uv run ruff format --check .` → exit 0.
- Compliance registry: `uv run python scripts/check-compliance.py` → exit 0.
- Quality / Agent store writes: `scripts/check-agent-store-writes.py` → exit 0.
- Quality / BFCL provenance: `scripts/vendor_bfcl.py --check` → exit 0
  (13 artifacts + shim).
- Quality / Architecture fitness: `PYTHONPATH=packages/maistro-core/src
  uv run pytest packages/maistro-core/tests/fitness -q --timeout=30` →
  **39 passed**, exit 0.
- Quality / Acceptance state (CI-exact PR form): disposable lane container
  `cr2110b-ac-pg18` (pgvector/pgvector:pg18, port 15501, reused), fresh
  `maistro_test` DB, `uv run alembic upgrade head` (→068), then
  `DATABASE_URL=MAISTRO_TEST_PG_DSN=RATCHET_BASE_REV=origin/develop
  scripts/check-ac-state.py --run-tests --ratchet --mandate d0e8e235a896…`
  → **exit 0**: ratchet OK (10 counters on ceilings, 1 progress counter on
  its floor, folded from 49 notes at d0e8e235; authorized floor
  design_coverage ≥ 39.641 per the owner-authorized #166 grant),
  acceptance mandate 0 added/0 unproven, chain mandate 0/0. This
  definitively refutes the stale "design_coverage 40.37 < floor 44.46"
  finding — the measured base grant governs and the branch passes.
- exact-debt-ledger / vulture, CI's exact arguments:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; **1236
  reviewed identities == 1236 findings**, unclassified 0, never-allowlist
  0. No unbanked identities → **no ledger amendment needed this round**.
- Suite inventory: `scripts/check-suite-inventory.py` → ok, 21 suites,
  35493 unique identities; `docs/testing/inventory-notes/security-windows-
  policy-prerequisite.md` (+3) still accurate — no tests changed this
  round, no inventory-note update required. `check-test-duplicates.py` →
  ok, 0 groups.
- Closure keywords: `git log --format='%s %b' d0e8e235..HEAD | grep -Eiw
  'fixes|closes|resolves…'` → no match (exit 1); PR body likewise clean.

## Residual limits (unchanged, declared)

- Real Windows policy enforcement, PowerShell 5.1, UAC elevation, RunOnce
  post-reboot resume, and reboot remain unexercised locally (no Windows
  host; only pwsh 7.4.6).
- The required `test` check stays red repo-wide (base included) until
  picomatch publishes a patched release; clearing it requires a
  dependency-repair lane or a deliberate, authorized audit-floor decision.
  No GitHub mutation is available to this lane to reconcile it.
- Hosted CI matrix legs that were skipped (service-gated Container scan
  variant) remain non-blocking by workflow design at this head.

Verdict: all issue acceptance criteria locally proven with executed
evidence; every historically-RED gate green at the exact head (hosted) and
re-proven locally where executable. Handoff-ready.

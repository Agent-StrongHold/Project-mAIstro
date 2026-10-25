---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
---
# L80 repair round 13 — both verifier findings resolved as non-defects; evidence committed

Verifier job `5aea5c52` (head `51730f26663655b381048e2ffe45d188304eb587`,
base `0456938b69e1b30c5103079308b876dbb2dd8330`) returned NEEDS-REPAIR with
two findings. This round re-derived both from primary evidence at the same
head and records the outcome as a commit. No code delta was warranted: the
sandbox under test is unchanged and every functional gate is green.

## Finding 1 — "check-vulture-baseline.py exited 1; 1440 vs 1402": invocation-scope artifact, CI gate is green

The verifier ran the script with **no path arguments**. The script's default
scope (`scripts/check-vulture-baseline.py`, `main()`) is
`packages tests --exclude "*/.venv/*,*/node_modules/*"` — a strictly wider
surface (hive-conductor `backend/`, `dags/`, `eval/`, maistro-canvas
`frontend/server`, maistro-evolve `third_party`, all `tests/` trees) than the
per-identity ledger was banked for. Under that wider scope vulture resolves
more callers (541 recorded `core-public-api-surface` identities stop being
"unused") and covers unbanked trees (204 unbanked
`fastapi-route-handler` identities in `packages/hive-conductor/backend/...`
alone), hence 1440 findings vs 1402 ledger rows and exit 1.

That invocation is **not a CI gate**:

- Both workflows invoke the scoped command and only the scoped command:
  `.github/workflows/quality.yml` ("vulture (dead-code; confidence ≥ 60 —
  per-identity ledger)" step) and `.github/workflows/vulture-ratchet.yml`
  ("Require exact reviewed Vulture identities" step) run
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`.
- The unscoped call in `scripts/run-quality-scans.sh` wraps its invocation in
  `|| { echo "WARN: ... treating optional scanner as advisory"; }` — it can
  never fail a gate — and `run-quality-scans.sh` is referenced by no workflow
  (only `scripts/install-quality-scanners.sh`).

Re-proven at this head (exit code captured):

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**,
  `1402 reviewed identities -> 1402 findings`, `unclassified: 0`,
  `never_allowlist: 0` — zero unbanked, zero stale. The lane-brief directive
  "fix what is genuinely dead, amend the ledger for reviewed retained
  identities" is therefore a no-op: there is nothing to fix or amend at the
  CI scope. Mass-banking the unscoped-scope identities would bank unreviewed
  findings from vendored/frontend/test trees, which the ledger's reviewed
  per-identity contract forbids.

## Finding 2 — "PR #1450 checks QUEUED": still in flight GitHub-side; locally proven green at the same head

Read-only `gh pr view 1450 --repo Agent-StrongHold/Project-mAIstro` (no
mutation) this round: `headRefOid == 51730f26663655b381048e2ffe45d188304eb587`
(exactly this branch head); statusCheckRollup = 12 QUEUED, 2 IN_PROGRESS,
6 COMPLETED/SUCCESS, 1 COMPLETED/SKIPPED. The queued set includes
`exact-debt-ledger` (the vulture per-identity gate) — the identical scoped
command proven exit-0 above, and `Vulture Ratchet`/`lint-and-type-check`-style
gates proven green locally. CI execution itself cannot be advanced from this
environment (no-push/no-mutation rule); it remains the one UNVERIFIED-by-CI
item, with the underlying commands verified at the exact head under test.

## Acceptance battery re-run at this head (all fresh executions)

- Docker 29.7.2 live conformance against the production
  `ContainerBuilderSandbox`: `uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q` →
  **33 passed** (escape classes: filesystem, path escape, network
  default-deny, non-root exec, credential seed denylist, env default-deny,
  read-only rootfs + writable scope, process/namespace/device/host-socket,
  timeout kill incl. detached descendants, cleanup, memory exhaustion).
- Bubblewrap Tier-3 lane `uv run pytest
  packages/maistro-core/tests/sandbox/test_escape_conformance.py -q` →
  **4 passed, 24 skipped**; skip reason captured:
  "this host cannot build a bubblewrap sandbox" (fail-closed skip; the CI
  lane installs bubblewrap — `.github/workflows/ci.yml` "Run the real Builder
  sandbox conformance lane" — so the skipped assertions execute there).
- `uv run ruff check .` → clean; `uv run ruff format --check .` →
  "2590 files already formatted".
- Suite inventories: `scripts/check-suite-inventory.py` for
  `packages/maistro-bootstrap/tests` and `packages/maistro-rsi/tests` → ok.
- SECURITY.md conformance evidence present (limitation #8 block citing the
  production Docker backend's filesystem/process/namespace/network/device/
  host-socket/credential/privilege coverage and the Bubblewrap lane).

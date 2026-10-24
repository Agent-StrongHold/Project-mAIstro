# atomic-admission-1893 — CI observed green at head 27c43e7fc

Repair-follow-up round for the #1893 lane at branch `auto-1893`. Starting and
ending head `27c43e7fc302a1e3ee3afcdc3266d8ca5049e31e` (exact head the prior
verify round flagged); develop base `b9cd15c60`. The previous round
(`atomic-admission-1893-repair-develop-sync-638b5738c.md`) reproduced every
scanner leg of the failed `security` jobs locally but disclosed that a green
GitHub CI run at the head was "the only proof" still missing. This round
closes exactly that gap: **no code change, no test change** — the round
observes CI at the recorded head and re-runs the ledger gates locally.

inventory-delta:
  packages/maistro-core/tests: +0

## Prior findings addressed

1. **"ci.yml containers job not observed green at head 27c43e7f…"** — now
   observed green. The `security` workflow run
   [39897059618](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/39897059618)
   (event `pull_request`, branch `auto-1893`, headSha
   `27c43e7fc302a1e3ee3afcdc3266d8ca5049e31e`, created 2026-10-23T03:49:35Z)
   completed with conclusion **success**; per-job:
   `Container scan + SBOM + cosign` → success,
   `Supply chain (pip-audit)` → success, `SAST / Bandit`,
   `SAST / Gitleaks`, `SAST / Semgrep`, `SAST (bandit + semgrep + gitleaks)`
   → all success. These are the exact three jobs that failed at 82756b5
   (runs 39834990868 / 120020826862 / 120020827244 / 120020828374).
2. **"recovery budget exhausted — /home/dev/fleet-ops/agents/maistro-implementer.md
   missing at implementer launch/preflight"** — infra-only, not a tree defect;
   the file exists in the current environment (launched fine this round).

## Full CI rollup at head 27c43e7fc (read-only `gh` observation)

Every check on PR #1945 at this headSha is SUCCESS, SKIPPED, or NEUTRAL —
a filtered rollup query for any other conclusion returns **0 rows**:

- `CI` run 39897059651 → **success**: `test`, `lint-and-type-check`,
  `security`, `docker-build`, `postgres (pg17)`, `postgres (pg18)`,
  `hive-conductor-e2e`, `hive-conductor-e2e-ui`, `cross-product-parity`,
  `wheel-imports`, `strike-ladder`, `Compliance registry`, `pr-base`,
  `workflow-lint` all success (`durable-events`, `object storage (MinIO)`
  skipped by design).
- `quality` run 39897059500 → **success**: all `Quality / *` jobs plus
  `Coverage gate (publish-set floor + diff coverage)` success.
- `security` run 39897059618 → **success** (see above).
- `Vulture Ratchet` 39897059488, `exact-debt-ledger`, `Gate C`,
  `Cage Guard`, `Registry CI`, `DevSkim`, `Formal Conformance`,
  `Integration Scope` → all success. PR state OPEN, `mergeable: MERGEABLE`.

## Local gate re-runs at this head (writer validation)

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1314 reviewed
  identities → 1309 findings, unclassified 0, never_allowlist 0, base
  b9cd15c608b5, candidate 27c43e7fc302. **No ledger amendment needed.**
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability.py`
  → exit 0 (1452 modules, 157 unreachable);
  `check-reachability-provenance.py` → OK 157→157, no candidate-approved
  expansion; `check-reachability-dispositions.py` → OK (47 groups: 136
  CONNECT, 20 LIBRARY, 1 RETIRE); `check-reachability-dispositions-provenance.py`
  → exit 0.
- `uv run python scripts/check-ratchet-provenance.py` → exit 0 (0 lifecycle
  violations; 54 quality JSON consumers with explicit provenance).
- `uv run python scripts/check-image-pins.py` → 8 pins / 10 Dockerfiles, ok.
- `uv run python scripts/check-merge-markers.py` → ok.
- Driver verifier checks in job dir (all returncode 0): `uv sync --locked
  --extra dev`, `ruff check .` (All checks passed), `ruff format --check .`
  (3467 files), focused pytest `test_cli_lock.py test_pack_contracts.py
  test_admission_codec.py` → 273 passed, 3 skipped,
  `check-suite-inventory.py --suite packages/maistro-core/tests` → ok,
  17627 unique node IDs, delta +0.
- Tree delta vs the locally-validated head 638b5738c is docs-only (this
  note's predecessor, +99 lines), so all build/scan evidence from that round
  applies unchanged to this head; CI has now independently confirmed the
  container build + scan + SBOM legs end to end.

## Acceptance

- All three CI jobs that failed at 82756b5 are green **at the exact head**
  `27c43e7fc302…` (run 39897059618), plus the full rollup has zero
  non-success checks and the PR is mergeable.
- Vulture per-identity ledger: PASS at CI argv, no amendment required.
- All reachability/ratchet/pins/markers gates: PASS locally at this head.
- No production activation, no SQL/HTTP/queue change (`git diff b9cd15c60..
  HEAD -- packages/` touches only admission_codec.py, its tests, two
  extension test files, runs/__init__.py +2 export, _vulture_whitelist.py),
  no competing execution authority introduced.

## Residual risks

- None known in the tree. CI conclusions can regress only with new pushes;
  this branch took no push action (lane prohibition) — the green run was
  triggered upstream on the already-open PR #1945 at this same SHA.
- `durable-events` and `object storage (MinIO)` CI jobs are `skipped`
  (conditional paths), unchanged from trunk behavior.

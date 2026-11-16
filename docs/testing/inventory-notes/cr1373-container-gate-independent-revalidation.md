---
inventory-delta:
  tests/: +0
---

# Independent re-validation of the container-gate repair at `b455001e2`

Round-4 validation of the "Container scan + SBOM + cosign" repair
(`b868e47f9` -> `4295a40c1` -> `b455001e2`). No source, test, workflow or
ledger file changed in this round: every image the CI job builds was
**rebuilt from this tree** with the job's own build arguments and
`--no-cache-filter` stages, and every scanner/gate step of that job was
re-run locally with CI's pinned tool versions. Nothing below relies on a
previous round's claim.

## Images rebuilt from this tree (CI-exact build lines)

| image | build flags | interpreter |
|---|---|---|
| `hive-conductor:pr-cr1373-reval` | `--build-arg VITE_POC_MODE=pm --build-arg VITE_BASE_PATH=/pm/ --no-cache-filter runtime-apt` | 3.13.18 |
| `hive-conductor-observability:pr-cr1373-reval` | `+ --build-arg INSTALL_OBSERVABILITY=1` | 3.13.18 |
| `maistro-engine:pr-cr1373-reval` | `--no-cache-filter runtime-apt` | 3.13.18 |
| `maistro-engine-research:pr-cr1373-reval` | `--no-cache-filter production-apt` | 3.12.16 |
| `maistro-rsi-runner:pr-cr1373-reval` | `--no-cache-filter runtime-apt` | 3.12.16 |

Base pins re-verified live against Docker Hub before trusting the builds:
`python:3.13.18-slim-bookworm` resolves to
`sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72`
(interpreter 3.13.18) and `python:3.12-slim` to
`sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`
(interpreter 3.12.16) — exactly the two `quality/image-pins.json` rows the
repair refreshed, and `scripts/check-image-pins.py` exits 0 over the tree.

## Scanner legs (CI's pinned versions, CI's arguments)

- trivy **0.73.0** `image --severity HIGH,CRITICAL --ignore-unfixed
  --exit-code 1 --ignorefile .trivyignore.yaml` exits **0** on
  hive-conductor, maistro-engine, maistro-engine-research and
  maistro-rsi-runner.
- grype **0.116.0** `<image> --fail-on high --only-fixed --output table`
  exits **0** on the same four. No HIGH finding with a published fix
  survives on any of them; `usr/local/bin/docker` reports
  `Docker version v29.9.3, build 5457199` and carries zero fixed gobinary
  findings (the go-jose/v4 4.1.5 + x/net 0.60.0 pair the `4295a40c1` repair
  removed).
- `security.yml`'s two live verification commands pass verbatim against the
  rebuilt images: `identity=operational python=3.13.18 bip-utils=2.12.2
  coincurve=21.0.0 pynacl=1.6.2` and `observability=importable
  identity=operational python=3.13.18`.
- The research image ships the versions the lock floors were written for:
  oauthlib 4.0.1, pyasn1 0.6.5, pypdf 7.1.0, soupsieve 4.1.1,
  patchright 1.64.4, playwright 1.65.2 (browser-use 0.5.9), and the
  bs4 -> soupsieve CSS path (`soup.select('p.x')`) is exercised in-image.
  `maistro-rsi-runner` ships temporalio 1.36.1 / nexus-rpc 1.5.0.

## The remaining steps of the same CI job

- **Reconcile installed packages to uv.lock** — `uv export --locked` +
  `scripts/check-image-lock-reconciliation.py` exits 0 for all four images
  (engine 126 distributions, hive-conductor 73, research 147, rsi-runner
  220; each "ships exactly the locked set").
- **Frontend license surfaces** — `npm ci` + `npm run build` for both
  `packages/hive-conductor/frontend` and `packages/maistro-canvas/frontend`.
- **SBOMs + license inventory** — syft 1.49.0 CycloneDX SBOMs for the four
  images, the extracted `hive-conductor:/app/frontend/dist` bundle and both
  npm trees, then `scripts/check-license-inventory.py` with
  `quality/license-policy.json`: exit 0, 8 surfaces / 25292 components,
  copyleft=419 (policy action is *review*, not fail).

## Repair-round gates and batteries

- `scripts/pip_audit_gate.py` (supply-chain job, strict `pip-audit`):
  exit 0 — only the pre-existing triaged `ecdsa==0.19.2 PYSEC-2026-1325`
  row.
- CI-exact vulture ledger: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> 1238 reviewed
  identities -> 1238 findings, exit 0. **No ledger amendment was needed**;
  `git diff --numstat origin/develop...HEAD -- quality/` is only
  `ac-state-notes/auto-62.json +17` and `image-pins.json 9/9`, so no
  vulture/radon/promotion/reachability/authorization row moved.
- Also exit 0: `check-dependency-namespaces`, `check-image-inventory`,
  `check-durable-table-inventory`, `check-radon-baseline` (126/126),
  `check-promotion-surface`, `check-reachability-dispositions`,
  `check-execution-lifecycles` (19/19), `check-convergence-matrix`,
  `check-m1-convergence-freeze --base origin/develop`,
  `check-ratchet-provenance`, `check-backlog-consistency`,
  `check-merge-markers`, `uv lock --check`.
- ruff check + ruff format --check clean; mypy clean (952 source files).
- Both per-suite inventories match: Hive 4,199 / Core 18,500.

## Behavior, with the PostgreSQL legs actually running

A fresh `pgvector/pgvector:pg18` scratch database
(`cr1373-reval-pg`, `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@
127.0.0.1:5599/maistro_test`) was migrated with `uv run alembic upgrade
head` and used for every run below, so the PostgreSQL parametrizations ran
instead of skipping:

- M1-E2 focused battery (delegate, guest peers, cross-store crash
  reconciliation, m1_e2 recovery convergence, stores gaps, remote delegate
  node): **281 passed, 0 skipped** (250 passed / 31 skipped without a
  server).
- Full `packages/maistro-core/tests/graph/durable_runs`: **871 passed,
  4 xfailed, 0 skipped**.
- `packages/maistro-core/tests/a2a`: 295 passed.
- Conductor crash recovery (`test_dag_recovery.py` +
  `test_registered_dag_recovery.py`): 28 passed.
- `tests/test_distribution_contract.py` +
  `tests/test_pinned_digest_references.py`: 14 passed; the pin-and-
  distribution slice of `tests/`: 405 passed, 3 skipped.

No test was added, removed or edited, so the recorded inventory counts are
unchanged (`tests/: +0`).

## Not claimed

Parent #62's process-restart (OS-kill) durability, the full production
admission/waker matrix, cross-release checkpoint compatibility and the
closure of children #837/#1151/#1192 remain UNVERIFIED, exactly as
`cr1373-recovery-evidence-repair.md` records them. This round proves the
container gate and the repair-round batteries; it grants no integration
approval and performs no issue/PR mutation.

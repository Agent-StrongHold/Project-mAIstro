# Repair #859 — pip-audit advisory bump + acceptance-state re-bank + first-hand container-scan proof (branch auto-859), round at 02ea0e439

Starting head `02ea0e439affe` (assigned). The previous round's block — the
preserved develop-sync conflict — was already resolved before this round:
merge `c8ac7339e` (verify-restore.sh readiness conflict) plus the inventory
record `02ea0e439`; the worktree arrived clean at that head. Every claim below
was re-derived here, including re-running the prior round's verification.

## 1. Acceptance-state ratchet — the recorded re-bank (note only)

`quality/ac-state-notes/auto-859.json` banked `design_coverage: 44.1172`, but
the merged develop tip moved measured coverage to `44.2377`. Reproduced
exactly (see §4 for the environment that makes the number reproducible):

    DATABASE_URL/MAISTRO_TEST_PG_DSN=… RATCHET_BASE_REV=origin/develop \
      uv run python scripts/check-ac-state.py --run-tests --ratchet
    → FAIL: unbanked improvement — design_coverage: 44.2377, floor still says 44.1172

Repair per the gate's own instruction: one `--bank` run, one file, one line —
`design_coverage` 44.1172 → 44.2377. Re-run passes:

    OK: 10 debt counters sit exactly on their ceilings and 1 progress counter
    sits exactly on its floor (folded from 42 note(s) at a9fdec4cb40a)

Environment footnote: with only `--extra dev` synced the same command measures
`40.0778` (a spurious *fall*) because DSN/import-gated AC tests skip. CI's
`quality-acceptance` job syncs `--locked --all-extras`, installs
maistro-evolve + pytest-timeout, and uses a pgvector:pg18 service with plain
`postgresql://` DSNs — replicating that locally is what reproduces CI's number.

## 2. Supply chain (pip-audit) — the red job behind the `security` workflow

The containers job was already green at this head (check-runs 2026-10-22
19:24Z), but the `security` workflow stayed red via `Supply chain (pip-audit)`.
Reproduced with the workflow's exact steps
(`uv sync --locked --all-extras`; `uv pip install pip-audit`;
`uv pip freeze --exclude-editable`; `pip-audit --strict --format=json`;
`scripts/pip_audit_gate.py`):

    gitpython==3.1.62    CVE-2026-114145            → fixed in 3.2.1
    graphql-core==3.2.11 CVE-2026-75507, -75508     → fixed in 3.2.12

Fixed versions exist → upgrade, never ALLOWED (the gate's own rule). Both are
transitive test-tool deps (`gitpython ← cosmic-ray`, `graphql-core ← moto`;
neither ships in any image — verified `importlib.util.find_spec` inside the
built maistro-engine image returns None for both). Repair is lock-only:

    uv lock --upgrade-package gitpython --upgrade-package graphql-core
    → gitpython 3.1.62→3.2.1, graphql-core 3.2.11→3.3.0; uv sync --locked --all-extras

Gate after: `pip-audit OK (1 known, all triaged in ALLOWED)` — the remaining
`ecdsa==0.19.2 PYSEC-2026-1325` is the reviewed, no-fix-entry allowlist pair.

## 3. Container scan — first-hand reproduction at this head

Prior round's claim re-proven, not assumed. `docker build -f Dockerfile`
resolves the pinned base
`python:3.13.16-slim-bookworm@sha256:73aa5faee130…` (build succeeds FROM the
digest), and the built image scans clean:

    trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed \
      --ignorefile .trivyignore.yaml maistro-engine:pr-859-local
    → 0 findings, exit 0; in-image libexpat1 2.5.0-1+deb12u5

Supporting gates re-run: `scripts/check-image-pins.py` ok (8 pins / 10
Dockerfiles); `tests/test_pinned_digest_references.py` 8 passed;
`tests/test_backup_restore_oracle.py` + pinned-digest together 29 passed;
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` → 1314 reviewed = 1314 findings (ledger clean).

## 4. Fallout checks for the lock bump

- ruff check / format: clean; turing suites 350 passed; moto-consuming archive
  suite 128 passed; `import moto/graphql/git` all import at the new versions.
- `scripts/check-release-consistency.py` ok; `scripts/check-dependency-namespaces.py`
  no unreviewed top-level namespaces.
- The trivy-clean image predates the lock bump, but the bumped packages are not
  installed in the image (verified), so the scan evidence is unaffected.

## Residuals (not executed locally, unchanged from prior rounds)

- cosign signing and SBOM legs, and the hive-conductor / research / rsi-runner
  image builds+scans, run only in CI (no local cosign binary); containers job
  observed success at this head in the captured check-runs.
- The merge-queue re-evaluation after this commit is what finally retires the
  `security` workflow red; local evidence above covers both of its jobs.

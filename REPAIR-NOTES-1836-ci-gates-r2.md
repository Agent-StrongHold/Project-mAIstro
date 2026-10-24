# REPAIR-NOTES-1836 — CI-gate repair round 2 (branch auto-1836 @ 9caef3f2328a)

Assigned block: "Container scan + SBOM + cosign: failure" plus the carry-over
finding "Quality / Workflow inventory: `|| true` at security.yml:333 without a
written reason" (prior verify verdict NEEDS-REPAIR). Both fixed on evidence
read from the failing run's own logs, not guessed findings.

## 1. Container scan + SBOM + cosign — root cause: gate parser vs resolution fork

Failure evidence (gh run view 40093845270 --log-failed, step "Reconcile
installed packages to uv.lock"):

```
image maistro-engine:pr-2264 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

Chain of facts, all re-derived locally:

- The branch's `uv.lock` (from the lane's own `8d31f1806`, which ran
  `uv lock --upgrade-package fastmcp --upgrade-package setuptools` for the
  pip-audit advisories) legitimately forks beartype: 0.22.9 with
  resolution-markers `python_full_version == '3.14.*' / '3.13.*' / < '3.13'`,
  and a new 0.23.1 entry with `>= '3.15'`. develop's lock has only 0.22.9.
- `uv export --locked --package maistro-server --extra image --no-dev
  --no-emit-workspace --format requirements-txt` (run locally, identical to
  the CI step) lists BOTH lines with markers.
- The image is correct: `Dockerfile` installs from the same export via
  `--require-hashes` under `uv venv --python 3.13`, so it installs 0.22.9.
- The gate at `scripts/check-image-lock-reconciliation.py` was wrong:
  `parse_expected` kept one pin per name in a dict (last line wins → 0.23.1),
  so the image's correct fork read as a version skew. Nothing before this
  branch had ever produced a same-name fork in the export, so the collapse
  was latent.

Fix: `parse_expected` now classifies per line (unconditional vs conditional
sets of pins, several versions per name allowed); `main` builds a
name → set-of-locked-versions map and flags a skew only when the installed
version matches none of them; `missing` is evaluated by name so a required
name satisfied by a marked alternate fork is not a false red. Single-version
behavior is unchanged — the 28 pre-existing tests pass unmodified.

## 2. Quality / Workflow inventory — the swallow without a written reason

`security.yml:333` (`dpkg-query ... libbrotli1 || true`, added by
`9caef3f23`) had its nearest comment 13 lines up; the gate wants one on the
line or within 6 lines above. Added a 5-line reason comment directly above
the command: the dpkg line is forensic context only, the real gate is the
stamp assertion above it, and the swallow covers absence-of-package only.
`uv run python scripts/check-workflow-inventory.py` → rc 0 (was rc 1 with
exactly this finding, matching CI job 120871881107).

## Validation (true exit codes)

- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → 33 passed
  (27 baseline + 6 new). Fail-before: with the old script, exactly the 5 new
  regression-capturing tests fail (`5 failed, 28 passed`); the sixth (shipping
  the last fork's version) pins the other fork direction.
- `uv run python scripts/check-workflow-inventory.py` → rc 0, 31 workflows.
- `uv run python scripts/check-suite-inventory.py --suite tests/` → rc 0
  (expected 5880 == collected 5880, with the +6 delta note;
  `docs/testing/inventory-notes/1836-image-lock-reconcile-forks.md`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → rc 0: 1302 reviewed
  identities == 1302 findings, unclassified 0, never_allowlist 0. Nothing
  eliminated, nothing new — no ledger amendment (changes are in scripts/ and
  tests/, outside the scanned tree).
- `uv run ruff check .` / `uv run ruff format --check .` → clean (3484 files).
- Diff coverage of the changed script, measured with CI's producer shape
  (`coverage run --branch --source=scripts` over the suite →
  `check-diff-coverage.py --base 4de7e906d9dc`): 100% lines / 100% branch
  arcs on the changed file (post-commit re-run recorded in the commit's
  trail; the pre-commit run measured 0 files because the gate diffs
  committed state).

## Not addressed here, by design

- SPEC-101826-1836 owner acceptance remains open (status Proposed) — issue
  #1836 stays open; no closure actions taken.
- The other steps of run 40093845270's containers job were green; the only
  red step was the reconcile step fixed above.

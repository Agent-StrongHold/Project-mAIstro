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

## Round 3 — develop-sync re-anchor of the branch AC-state note (@ 4693f1f3d6b3)

Assigned carry-over (verify verdict NEEDS-REPAIR at 4693f1f3d): the branch
note `quality/ac-state-notes/auto-1836.json` still banked the **pre-merge**
measurement (design_coverage 44.2377, banked at 8d31f1806), while the
develop-sync merge 4693f1f3d moved the tree onto develop's doc corpus.
`check-ac-state --run-tests --ratchet` reproduced red:
`design_coverage: 39.641 falls below the floor of 44.2377`.

Root cause, read from the gate's own machinery (not guessed):

- The regression half of the ratchet was never the problem: the base fold at
  f956a8142 carries the owner-authorized grant `design_coverage@39.641`
  (`quality/ratchet-authorizations.json`, `ac-state`, #166, landed on develop
  at 2ac960614 — "Two-merge rule observed: this authorization lands before
  any candidate that needs it"), so the effective floor is 39.641 and the
  measured 39.641 passes it. Not superseded (`MIN_SUPERSEDING_NOTES = 3`;
  superseding-note count computed empty), not stale.
- What failed is the **exact comparison**: `_exact_target` raises the target
  by `_fresh_note_bound()` — notes new-or-different vs the base — and the
  stale branch note at 44.2377 pinned the exact target there ("below it is a
  regression the grant does not cover, above it is slack to bank").

Repair (exactly the gate's printed remedy — "bank the fall with --bank and
justify it in the diff"):

- `uv run python scripts/check-ac-state.py --run-tests --ratchet --bank` →
  re-banked the branch note at the actual measurement. Diff is the single
  counter `design_coverage: 44.2377 -> 39.641`; every debt counter and
  `measured_with_tests: true` unchanged. Justification lives in the diff via
  the #166 grant the base already carries (owner-authorized measured
  re-anchor; the folded floor 44.2377 came from a stacked-branch tree that
  never reflected a develop tip) plus this note.
- Re-ran the gate: `--run-tests --ratchet` → rc 0, "authorized floor:
  design_coverage may fall to 39.641 — #166 …", "OK: 10 debt counters sit
  exactly on their ceilings and 1 progress counter sits exactly on its
  floor". CI's PR shape `--run-tests --ratchet --mandate f956a814275c` →
  rc 0, "this change adds no spec, decision or criterion-less document to
  the chain".
- No-regression battery re-run at the post-fix tree: `ruff check .` clean,
  `ruff format --check .` clean (3484 files), `check-workflow-inventory.py`
  rc 0 (31 workflows dispositioned), `check-suite-inventory.py` rc 0
  (21 suites match), `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` rc 0 (1302 reviewed
  identities == 1302 findings — no ledger amendment needed or made).

Issue #1836 stays open; no closure actions.

# REPAIR-NOTES-1838 round 6 — containers gate: pypdf HIGH CVEs in maistro-engine-research

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; base `4de7e906d9dc` (= `origin/develop`, no sync conflict);
starting head `6ada316d5011` (round-5 commit, all other checks green there).

A prior attempt produced the pypdf lock bump but died on a provider 429 before
committing; the uncommitted `uv.lock` hunk was verified firsthand (hashes against
PyPI) and salvaged rather than regenerated or discarded.

## Incoming evidence (CI run 40070700145, job 120803289052, at `6ada316d5011`)

`Container scan + SBOM + cosign` was the only failing check of 72; the failing
step was **14 — "Trivy scan maistro-engine-research (HIGH/CRITICAL only)"**
(job log fetched via `gh api .../actions/jobs/120803289052/logs`; step table
reproduced from the check-runs payload). The scan's own table:

- `pypdf 6.21.1` — CVE-2026-115572, CVE-2026-115580, CVE-2026-115585
  (all HIGH, status **fixed**, Fixed Version **6.21.2**; "Possible long
  runtimes" ReDoS-class findings in pypdf parsing).
- Everything else in the image: 0 findings (debian 13.7, node-pkg
  patchright/playwright, all python-pkg METADATA, gobinary docker CLI).

pypdf reaches only this image: `browser-use==0.5.9` (maistro-core `browser`
extra → Dockerfile.research's `uv export --locked --package maistro-server
--extra observability --extra browser`) requires pypdf. pypdf is absent from the
maistro-server `--extra image` export (engine image) and both hive-conductor
exports — which is why steps 12/13 (hive-conductor, maistro-engine Trivy) passed
at the same head. `ignore-unfixed: true` makes an ignore entry the wrong tool:
the fix exists, so the gate's policy (and round-5 precedent) mandates upgrade.

## Repair (lockfile only; no gate, ledger, policy, or source edits)

- `uv.lock`: pypdf 6.21.1 → 6.21.2 (the salvage). Artifact hashes verified
  against PyPI's JSON API for 6.21.2 before trusting:
  sdist `0a3e1c5c…66551c2d4`, wheel `1d44d1a3…488007ea9254b` — both match the
  lock rows exactly. `uv lock --check` exit 0; `uv sync --locked` (dev and
  `--all-extras`) exit 0, so the lock stays manifest-consistent. No pyproject
  change (pypdf is transitive; browser-use's range admits 6.21.2).

## Post-repair evidence (all commands executed this round)

- **Rebuilt `maistro-engine-research:pr-2269-r6`** with the CI build shape
  (`docker buildx build --load -f Dockerfile.research --no-cache-filter
  production-apt`): exit 0; builder smoke inside passed; in-image
  `importlib.metadata` reports `pypdf 6.21.2`, `browser-use 0.5.9`.
- **Trivy 0.73.0** (exact CI-pinned version) with CI-exact flags
  `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml --scanners vuln,secret` on that image: **exit 0, zero
  HIGH/CRITICAL, zero secrets** (no vulnerability totals emitted at all;
  `pypdf-6.21.2.dist-info` row shows 0). This is the exact failing step, now
  proven green.
- **Step 15 (rsi-runner Trivy) was never reached in CI**, so it was proven too:
  rebuilt `maistro-rsi-runner:pr-2269-r6` (`--no-cache-filter runtime-apt`,
  exit 0) and ran the same Trivy invocation: **exit 0, zero findings**.
- **Grype cross-check leg** (step 16, skipped in CI): `grype --fail-on high
  --only-fixed` on both rebuilt images: exit 0 both.
- Engine/hive-conductor images: pypdf is absent from all three of their
  `uv export` install sets (verified by export grep, 0 matches), so this bump
  cannot change their Python layers; both passed the identical Trivy scans in
  CI at this exact head (steps 12/13), and their remaining variable is the
  forced `--no-cache-filter` apt stage they already passed with.
- **Supply chain (pip-audit)**, security.yml shape (`uv sync --locked
  --all-extras` → freeze → `pip-audit --strict`): audit exit 1 with only the
  triaged `ecdsa`/PYSEC-2026-1325 pair → `scripts/pip_audit_gate.py`:
  `pip-audit OK (1 known, all triaged in ALLOWED)` + usage OK → **gate exit 0**.
  ci.yml `security` shape (`--extra dev` freeze): **gate exit 0**. pypdf 6.21.2
  itself is clean in pip-audit's DB.
- Issue deterministic acceptance: `uv run python
  scripts/check-adr-status-language.py` → `ok: 0 baselined body-status
  contradiction(s)`; `git diff --check` clean.
- Vulture per-identity ledger, exact CI/lane-brief args
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1302 reviewed identities → 1302 findings, ratchet OK,
  **exit 0**. No ledger amendment required or made (zero source change).
- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `uv lock --check`: exit 0.

## Scope notes

- The pypdf bump is trunk CI debt (transitive of browser-use), not part of the
  #1838 decision deliverable; it is included because this is an explicit
  CI-repair round ordered to fix the named failing gate with local proof.
- The issue's owner-acceptance boundary is untouched: ADR-101826-2a63 remains
  `Proposed`, `contracts:`/`tests:` stay empty, the decision gate stays open.
  Nothing here resolves the decision or claims implementation.
- This round adds no tests → no suite-inventory delta and no inventory note.

## Residual risks

- The SBOM/license-inventory and cosign legs (steps 17+) were not exercised
  locally (they need the full four-image build + npm builds); they were green
  in the same job's ancestors and depend on the frontend trees, which this
  round does not touch. The frontend license surfaces were rebuilt and
  license-scanned green in round 5 and are unchanged since `6ada316d`.
- A brand-new advisory published after the local Trivy DB update could still
  fire on CI; that is inherent to trunk scanning and not addressable here.

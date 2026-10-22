# Repair notes — #363 container gate round (branch `auto-363`)

Round start: `d3f236ed959e8382c256e43270c09b0e95867f26` (clean tree).
This round's head after repair: merge commit `f4e2e340d` (merge of `origin/develop`
at `0179dfabe` into `auto-363`), plus this notes file.

## Failing gate

`Container scan + SBOM + cosign` (`.github/workflows/security.yml:200`) failed on
the last merge-queue evaluation. No CI log was supplied with the dispatch; the
driver-side "previous block" was a provider 404 (`nous/stepfun/step-5-preview:free`
model retirement) — infrastructure, not a repository defect, nothing to change in
the tree for it.

## Diagnosis

The queue evaluates the synthetic merge of the PR with `develop`. This branch was
68 commits ahead of a merge base that predated four `develop` commits
(`0179dfabe`, `780f1d340`, `a7a6dd9a2`, `8e7887188`), including the vite bump that
modifies `packages/maistro-canvas/frontend/package.json` + `package-lock.json` —
an input to the gate's "Build frontend license surfaces" step and to the
`canvas-npm-tree` / `canvas-frontend-bundle` SBOM surfaces. The branch had also
not re-built/re-scanned its four images after the pillow/certifi freeze bump
(`108d938ac`).

## Repair

1. `git fetch origin`; `git merge origin/develop` — merged clean (0 conflicts,
   `git merge-tree` preview agreed), commit `f4e2e340d`.
2. Re-built all five gate images from the merged tree
   (`hive-conductor`, `hive-conductor-observability`, `maistro-engine`,
   `maistro-engine-research`, `maistro-rsi-runner`, tag `pr-363-r4`).
3. Re-ran the full gate locally, CI versions (trivy 0.73.0, grype 0.116.0,
   syft 1.49.0).

## Local proof (all at merged head `f4e2e340d`)

- Canvas + hive-conductor frontends: `npm ci` (0 vulnerabilities) + `npm run build` OK.
- Identity contract `docker run` checks: both print `identity=operational python=3.13.16 …`.
- Trivy `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml` × 4 images: exit 0 each, 0 findings (CI's `trivyignores`
  input maps to the CLI's `--ignorefile`).
- Grype `--fail-on high --only-fixed` × 4 images: exit 0 each.
- Syft: 4 image SBOMs + extracted `hive-conductor` `/app/frontend/dist` bundle +
  both npm trees + both built bundles → 8 CycloneDX SBOMs.
- `scripts/check-license-inventory.py` with the CI argument set: `OK: inventoried
  8 surface(s), 25929 component(s); copyleft=426 (policy=review)`, exit 0.
- Deterministic battery at merged head: `uv sync --locked --extra dev` OK;
  `ruff check .` clean; `ruff format --check .` 3388 files formatted;
  targeted pytest (`maistro-core` goal/run contexts, `maistro-server` worker yaml,
  `maistro-rsi` gate evidence, `hive-conductor` goal inspection) 111 passed,
  13 skipped; `mypy` on the seven library `src` trees: 913 files, no issues;
  `check-suite-inventory.py` for the four merge-touched suites: all match;
  `check-vulture-baseline.py` (CI args): 1324 reviewed identities → 1324
  findings, 0 unclassified; `check-ratchet-provenance.py`: OK;
  `check-image-pins.py`: 8 pins / 10 Dockerfiles registered, exit 0.
- `quality/*.json` row counts identical to pre-merge head `d3f236ed9` — the merge
  lost no ledger rows (the 19+/24− `image-pins.json` delta vs `develop` predates
  this round, from the `108d938ac` freeze bump).

## Not addressed here (pre-existing, out of this round's scope)

- `release.yml` promote-before-gate ordering and release-asset attachment of the
  inventory (prior findings) — release-path work, unchanged by this round.
- No tests added or removed by this round: no inventory-notes delta required;
  recorded suite inventories verified unchanged.

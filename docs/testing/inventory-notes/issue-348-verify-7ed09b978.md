---
inventory-delta:
  tests/: +0
---
# issue-348-verify-7ed09b978

Repair/verification round for #348 in worktree `auto-348` at head
`7ed09b9785e7` (the prior round's docs-only note on top of the validated merge
`000f08f0e03f`). No pytest tests were added or removed — `tests/:` is +0 — and
`git diff 000f08f0e..7ed09b978` is exactly the prior round's inventory note
(no image-relevant surface changed), so the four images the prior round built
at `000f08f0e` are builds of this head's source. This round re-executed the
deterministic battery and the shipped-vs-locked reconciliation first-hand at
this head.

## Evidence (executed first-hand at this head)

- `uv sync --locked --extra dev` OK; `uv run ruff check .` OK;
  `uv run ruff format --check .` OK (3439 files already formatted).
- `uv lock --check` clean (468 packages).
- `uv run pytest tests/test_image_lock_contract.py
  tests/test_distribution_contract.py tests/test_dependency_namespaces.py
  tests/test_engine_canvas_packaging.py` → 107 passed, 3 skipped (the skips
  are the MAISTRO_ENGINE_IMAGE-gated artifact tests).
- Security.yml's exact four `uv export --locked` exports + reconciliation
  gate re-run against the built images: `maistro-engine:verify-000f08f0e`
  ships exactly the locked set (128 dists), `hive-conductor:verify-000f08f0e`
  (72), `maistro-research:verify-000f08f0e` (148),
  `maistro-rsi-runner:verify-000f08f0e` (220) — all four OK at this head.
- AC-5 re-executed: `maistro-engine:rebuild-a` vs `rebuild-b` (two
  independent `--no-cache` builds) → byte-identical 128-distribution
  manifests (`diff -u` clean). Job `docker-rebuild-compare` at
  `.github/workflows/ci.yml:1295`; required check registered at
  `.github/branch-protection.json:108` and `docs/ci/REQUIRED-CHECKS.md:105`.
- Install mechanism re-read in all production Dockerfiles at this head:
  `Dockerfile:99-105`, `Dockerfile.research:84-91`,
  `packages/hive-conductor/Dockerfile:116-125` (hashed export +
  `--require-hashes` + `--no-deps` members), `Dockerfile.rsi-runner:126`
  (`uv sync --locked --extra rsi-fitness`), `deploy/sbx/template/Dockerfile:68-75`.
- Gates: `scripts/check-suite-inventory.py` (21 suites match),
  `scripts/check-image-pins.py` (8 pins across 10 Dockerfiles).
- `git diff --numstat <develop base> -- quality/` → only
  `quality/image-pins.json` (+4/-2, the intended pin rows); no ledger rows
  lost.
- No `#348` closure keywords in the lane's commits; keyword hits in the range
  are inherited develop-side history for unrelated issues.

## Not executed here (CI-side, unchanged scope)

The trivy/grype/syft scan executions and the pip-audit gate run in GitHub
Actions (`security.yml`: pip-audit at :160-197, trivy at :298, reconcile step
at :440-477 running on the built PR images after the SBOM steps); wiring
re-read this round. AC-2 red-controls and the engine pip-free check were
proven first-hand at `000f08f0e` (identical source); AC-6 wheel availability
for cp313/cp312 linux/amd64 was proven by those builds' hash-verified
downloads of every locked artifact.

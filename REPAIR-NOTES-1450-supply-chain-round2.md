# Repair notes — issue #1450 round 2 (CI supply-chain gate repair)

Branch `auto-80`, head before this round: `58138f6738d9` (already contains develop
tip `f8a2df966` merged — merge-base HEAD..origin/develop equals `origin/develop`,
so no develop conflict remains).

## Root cause of the reported CI failures

The merge-queue evaluation at `58138f673` failed three jobs:

- `Supply chain (pip-audit)` (security.yml) — `pip-audit found advisories outside
  the triaged allowlist`
- `security` (ci.yml) — same trunk-level failure; both jobs share the single
  verdict script `scripts/pip_audit_gate.py`
- `Container scan + SBOM + cosign` (security.yml) — Trivy/Grype scan the same
  locked Python dependency set inside the images

Local CI-exact reproduction (`uv pip freeze --exclude-editable` →
`uv run pip-audit --strict --format=json -r /tmp/deps.txt` →
`scripts/pip_audit_gate.py`) showed four untriaged advisories, all present on
develop as well (this branch changed no dependency manifests before this round):

| package            | locked    | advisory          | fixed version |
|--------------------|-----------|-------------------|---------------|
| dnspython          | 2.9.0     | CVE-2026-128089   | 2.9.2         |
| graphql-core       | 3.3.0     | CVE-2026-119286   | 3.3.1         |
| joserfc (authlib)  | 1.7.5     | CVE-2026-119284   | 1.7.6         |
| opentelemetry-api  | 1.45.1    | CVE-2026-126360   | 1.45.2        |

The gate's own policy (its failure output) says: upgrade when a fixed version
exists; only `ALLOWED` triage when none exists. All four have fixes, so the
repair is a lock upgrade, not a ledger edit.

## Fix

`uv lock --upgrade-package` for the four packages (plus the matching
opentelemetry family bump the resolver applies: sdk 1.45.2,
semantic-conventions 0.66b2). graphql-core resolves past the advisory fix
version to 3.3.2 and joserfc to 1.8.0; all specifiers are satisfied. Only
`uv.lock` changed — no `pyproject.toml` constraints needed widening.

## Evidence (all executed locally at the repaired head)

- `uv sync --locked --all-extras` → clean
- CI-exact pip-audit gate → `pip-audit OK (1 known, all triaged in ALLOWED)`,
  exit 0; the sole remaining advisory is the reviewed
  `ecdsa PYSEC-2026-1325` entry (no upstream fix, documented rationale)
- direct-dependency usage ratchet inside the same gate → OK (66 runtime deps,
  4 reviewed dispositions)
- `packages/maistro-core/tests/observability` → 174 passed (opentelemetry bump)
- `packages/maistro-server/tests/test_entrypoint.py + test_import_surface.py`
  → 8 passed (fastmcp/graphql-core/authlib import surfaces)
- CI-exact sandbox conformance lane (ci.yml final command,
  `DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests`) → **306 passed, 3 skipped** against the
  real rootless daemon — issue #1450 acceptance unchanged at the new lock
- `ruff check .` all passed; `ruff format --check .` 3562 files formatted
- `check-suite-inventory.py --suite packages/maistro-bootstrap/tests` → ok
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → RC=0, 1238 reviewed identities = 1238 findings
- `quality/` vs `origin/develop`: only the intended branch deltas remain
  (ac-state-notes append, image-inventory/image-pins rows for the test-only
  sandbox image); no ledger row loss

## Residual risk

The `Container scan + SBOM + cosign` job needs GitHub runners (GHA buildx
cache, cosign key) and was not rebuilt end-to-end locally. The Python
dependency CVE surface it scans is exactly the set fixed here; OS-layer
advisories are untouched by this branch and remain covered by the existing
documented `.trivyignore.yaml` triages. No test counts changed → no inventory
note delta required.

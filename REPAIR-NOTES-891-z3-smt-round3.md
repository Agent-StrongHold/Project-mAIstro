# Repair round — #891 (M8-A11 Z3/SMT research leaf), round 3, head `fd3a7ef18`

Round: L891 repair, job `a4ab496667d145fbae609298d3d192d4`, starting head
`fd3a7ef18137eec7f590c61a0eee2eafdb890e2e` (exact match), develop base
`a9fdec4cb40a62ada3e897448eabc81f2410135a` (already an ancestor of HEAD at
round start — the round-2 develop sync was complete before this round).

## The three failing CI legs at `fd3a7ef18` (check-run IDs from the live API)

| Check run | Job | Failing step (from `GET /actions/jobs/{id}`) | Root cause |
|---|---|---|---|
| 119987367008 | Supply chain (pip-audit) | `pip-audit (strict; retry…)` | `pip_audit_gate.py` exit 1: gitpython==3.1.62 CVE-2026-114145, graphql-core==3.2.11 CVE-2026-75507/75508 |
| 119987419185 | security | `Run python scripts/pip_audit_gate.py` | same advisories (same gate) |
| 119987367064 | Container scan + SBOM + cosign | `Trivy scan maistro-engine (HIGH/CRITICAL only)` | libexpat1 2.5.0-1+deb12u4 (CVE-2025-59375, CVE-2026-77214, HIGH, fixed 2.5.0-1+deb12u5) in the maistro-engine image |

Job-log evidence: the pip-audit excerpt in the dispatch
("pip-audit found advisories outside the triaged allowlist") is the gate
verdict, not the network-outage branch; the container log shows
`maistro-engine:pr-2238 (debian 12.15) Total: 2 (HIGH: 2)` on libexpat1,
with the hive-conductor scan (same job) clean.

## Repair 1 — supply chain: floor the two dev-only transitive advisories

gitpython arrives via cosmic-ray, graphql-core via moto[server]; both
dev-only, neither ships in any runtime image. Per the aiohttp precedent,
added `gitpython>=3.2.1` and `graphql-core>=3.3.0` to
`[tool.uv] constraint-dependencies` (pyproject.toml) and re-locked. The lock
moves only those two packages (260 → 260); graphql-core resolves to the
stable 3.3.0 (2026-09-27), not the rc the advisory text names. No global
prerelease-mode was introduced (the intermediate `--prerelease=allow`
mutation was backed out and re-locked clean).

**Proof (CI-exact sequence)**: `uv sync --locked --all-extras` →
`uv pip install pip-audit` → `uv pip freeze --exclude-editable` →
`pip-audit --strict --format=json -r deps.txt` →
`python scripts/pip_audit_gate.py` → **gate exit 0**
("pip-audit OK (1 known, all triaged in ALLOWED)"; the only remaining
advisory is the triaged ecdsa PYSEC-2026-1325).
Consumer compat: moto archive suite **128 passed** on graphql-core 3.3.0
(packages/maistro-core/tests/archive); cosmic-ray imports on gitpython 3.2.1
(mutation.yml runs on neither PRs nor schedules).

## Repair 2 — container gate: refresh the bookworm base pin (gha-cache poisoning)

`Dockerfile`'s runtime stage already runs `apt-get upgrade -y`, but the
buildx gha cache keys the apt layer on the pinned base digest, so a Debian
fix published after the layer was cached never reaches the image. Repair
(matches the #363/#2209/#1152 pin-refresh convention): refresh
`python:3.13.16-slim-bookworm` `a1165e27…` → `73aa5fae…` — re-verified live
from the registry before pinning: same tag, bookworm 12.15, CPython 3.13.16,
apt candidate libexpat1 **2.5.0-1+deb12u5** — in `Dockerfile` (builder +
runtime), `packages/hive-conductor/Dockerfile` (pybuild + runtime),
`scripts/smoke-engine-canvas.sh` CONTROL_IMAGE, and the
`quality/image-pins.json` row (recorded 2026-10-22, #2238). The trixie-based
`python:3.12-slim` pin is deliberately untouched (deb12u* does not apply).

**Proof (CI-exact local rebuild + scan, docker 29.1.3)**:
- `docker build -f Dockerfile -t maistro-engine:pr-2238 .` → exit 0;
  in-image `dpkg-query`: **libexpat1 2.5.0-1+deb12u5**,
  docker CLI v29.9.1 (dfc520d) on go1.27.3.
- trivy **0.73.0**, CI-exact flags (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml`): maistro-engine
  **exit 0** (debian + gobinary + python-pkg all clean — the exact step that
  failed in CI); hive-conductor **exit 0** (debian 12.15, 0 findings).
- grype **v0.116.0** `--fail-on high --only-fixed`: exit 0 on both images
  (two Medium CPython-binary rows only, below the gate threshold).
- Workflow's in-image identity assertion passes in the rebuilt
  hive-conductor: `identity=operational python=3.13.16 bip-utils=2.12.1
  coincurve=21.0.0 pynacl=1.6.2`.

## Guard test added

`tests/test_pinned_digest_references.py` (8 node IDs, inventory-noted in
`docs/testing/inventory-notes/2238-container-gate-base-pin-refresh.md`):
check-image-pins.py closes the pin registry against Dockerfiles only, so a
refresh that misses a non-Dockerfile pinned reference (the smoke script's
CONTROL_IMAGE) ships silently. The suite requires every registered
non-Dockerfile reference to match image-pins.json verbatim, the control
image to anchor to a pin row a Dockerfile builds from, a stale digest of a
registered image:tag to be rejected, and pins the scanner shape.
Demonstrated against the regression: re-running the suite's core predicate
against the pre-repair smoke-script line flags exactly the drifted
`a1165e27…` ref.

## Validation battery this round (all live, this worktree)

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3453 files already formatted |
| `uv run pytest tests/test_pinned_digest_references.py -q` | 8 passed |
| `uv run python scripts/check-image-pins.py` | 8 pins / 10 Dockerfiles, exit 0 |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | ok (5810 = baseline + 8) |
| pip-audit gate (CI-exact) | exit 0 |
| `uv run pytest packages/maistro-core/tests/archive -q` | 128 passed |
| `uv run pytest packages/maistro-core/tests/scheduling/_z3_fire_contract.py packages/maistro-core/tests/scheduling/test_engine_z3_conformance.py -q` | 13 passed (research deliverable intact) |
| `uv run python scripts/check-doc-links.py` | 0 broken |
| `uv run python scripts/check-backlog-consistency.py` | OK |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1314/1314 reviewed, exit 0 (ledger untouched — no src changes this round) |

## Residual risks

- Dockerfile.research / Dockerfile.rsi-runner images were not rebuilt
  locally (trixie base untouched by this round; their CI scans never ran
  because the job stopped at maistro-engine). Their only changed stage is
  the go1.27.3 docker-cli build, whose binary this round proved
  gobinary-clean inside maistro-engine.
- The engine canvas smoke's CONTROL_IMAGE contract is test-enforced but the
  smoke itself was not executed (needs a canvas-less control run plus the
  engine image; out of this round's scope).
- The gha cache poisoning mechanism remains structural: the next OS CVE in
  these images will need another digest refresh (now guarded by the new
  test for the non-Dockerfile surfaces).

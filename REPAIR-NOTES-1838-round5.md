# REPAIR-NOTES-1838 round 5 — CI-gate repair: trunk supply-chain advisories and npm audit debt

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; develop base `4de7e906d9dc` (= `origin/develop`, no sync conflict);
starting head `dbd5244e9399`.

## Incoming evidence (merge-queue evaluation at `dbd5244e9399`)

Four required checks failed: `Supply chain (pip-audit)`, `security` (ci.yml — same
gate script), `test`, `Container scan + SBOM + cosign`. The lane diff vs develop is
five markdown files (ADR + index row + prior round notes) — zero Python, npm,
Docker, or lockfile content — so none of these failures is caused by the lane's
deliverable; all four reproduce from trunk dependency state. `exact-debt-ledger`
and every Quality/* ratchet were already green at the starting head.

## Root causes (reproduced locally, not guessed)

1. **pip-audit gate (both `security.yml supply-chain` and ci.yml `security`)** —
   `uv sync --locked --all-extras` → `uv pip freeze` → `pip-audit --strict` →
   `scripts/pip_audit_gate.py` exited 1 with three advisories outside the triaged
   allowlist:
   - `fastmcp==4.0.11` GHSA-7xgj-8392-5q4r (fix 4.1.2)
   - `fastmcp==4.0.11` GHSA-vqqp-x5qm-5qp4 (fix 4.1.2)
   - `setuptools==84.0.0` GHSA-xmj3-9gf7-h52w (fix 84.1.0)
   The gate's own output prescribes the fix: upgrade the dependency; allowlist
   only when no fixed version exists. Both floors exist, so no ALLOWED edit.
2. **test job** — the failed step is `npm audit --audit-level=high` in
   `packages/maistro-canvas/frontend` (6 vulnerabilities: undici ×3 HIGH,
   zod HIGH, ip-address moderate ×3; all with `npm audit fix` available). Every
   pytest step that precedes it in the job was re-run locally and passed, so the
   `Event loop is closed` lines in the CI excerpt are log noise, not the failing
   step (GitHub Actions halts at the first failed step; npm audit is the step that
   failed with exit 1).
3. **Container scan + SBOM + cosign** — failure excerpt is the hive-conductor
   image build's npm stage. `npm ci` provably does not fail on audit findings
   (verified under the digest-pinned `node:22-alpine`, npm 10.9.9: exit 0 with the
   zod HIGH present), so the tree-side contributors were the hive frontend's zod
   HIGH in the npm tree plus whatever transient felled the build; both the build
   and the image-level scans were re-proven green after repair (below).

## Repairs (lockfiles only; no gate, ledger, or policy edits)

- `uv.lock`: `uv lock --upgrade-package fastmcp --upgrade-package setuptools`
  → fastmcp/fastmcp-slim 4.0.11→4.1.3, openapi-pydantic 0.5.1→0.6.0,
  setuptools 84.0.0→84.2.1, beartype dual-pin. All within declared ranges
  (root `fastmcp>=3.2.0`; maistro-core `fastmcp>=3.2.0,<5`); no pyproject change.
- `packages/maistro-canvas/frontend/package-lock.json`: `npm audit fix`
  (transitive bumps incl. undici, zod, ip-address; `package.json` untouched).
- `packages/hive-conductor/frontend/package-lock.json`: `npm audit fix` (zod HIGH).

## Post-repair evidence (all commands executed this round)

- pip-audit gate, security.yml shape (`--all-extras` freeze): audit exit 1 with
  only the triaged `ecdsa`/PYSEC-2026-1325 pair → `pip-audit OK (1 known, all
  triaged in ALLOWED)`; dependency-usage half OK → **gate exit 0**.
- pip-audit gate, ci.yml `security` shape (`--extra dev` freeze): **gate exit 0**.
- `scripts/check-dependency-namespaces.py` (#406): no unreviewed top-level
  namespaces after the bumps → exit 0.
- fastmcp consumers: `python -c "import maistro.tools.git.server;
  import maistro.tools.sandbox.server"` OK on fastmcp 4.1.3;
  `pytest packages/maistro-core/tests/tools` → 495 passed, 4 skipped.
- test-job pytest steps re-run with `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`:
  server 644 passed/8 skipped; turing 225; turing-backend 125; design 660/1 skip;
  ext-harness 273; ext-sdk 147; root `tests/ --ignore=tests/tools/registry`
  5638 passed/143 skipped. Zero `Event loop is closed` occurrences.
- Canvas frontend: `npm audit --audit-level=high` → 0 vulnerabilities, exit 0;
  `npm ci && npm run test:ci && npm run lint && npm run build` → 79 tests passed,
  lint 0 errors, build OK.
- Hive frontend: `npm audit --audit-level=high` → 0 vulnerabilities, exit 0;
  `npm ci && npm run lint && npm run build` → lint 0 errors, build OK;
  `dump-hive-openapi.py` + `npm run gen:api` → `types.gen.ts` byte-identical.
- hive-conductor image rebuilt from the repaired tree (`docker build -f
  packages/hive-conductor/Dockerfile`): end-to-end green; in-image identity
  contract smoke (python 3.13.16, bip-utils/coincurve/pynacl/msgpack/setuptools
  floors, ConductorSeed did:key) passed; Trivy 0.73.0 HIGH/CRITICAL
  `--ignore-unfixed` with the repo `.trivyignore.yaml` → **exit 0, no findings**.
- Issue deterministic acceptance: `uv run python scripts/check-adr-status-language.py`
  → ok (0 baselined contradictions) and `git diff --check` clean.
- `scripts/check-suite-inventory.py`: 21 suites match the recorded inventory
  (this round adds no tests, so no inventory delta and no inventory note).
- `ruff check .` / `ruff format --check .`: clean.
- Vulture per-identity ledger (exact command from the lane brief):
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302 reviewed identities → 1302 findings,
  ratchet OK, exit 0. No ledger amendment required or made.

## Adapter-contract facts re-verified firsthand (`biscuit-python==0.4.0` wheel)

Mint/attenuate/verify smoke on the pinned wheel: `BiscuitBuilder(datalog, params)`
+ in-place `set_root_key_id(0)` + `build(priv)`; `token.append(BlockBuilder(...))`;
`to_base64`/`from_base64(wire, public_key)`; `AuthorizerBuilder(policies, params)`
statement-style `set_time()` (no argument), fetch-mutate-set limits via
`AuthorizerBuilder.limits()` (fields writable) + `set_limits(limits)`;
`biscuit_auth.AuthorizerLimits` raises AttributeError (not exported); all six named
error types importable; `did:key` (multibase `z`, `0xed01` prefix, base58btc) ↔
raw-32-byte ↔ `PublicKey.from_bytes(raw, Algorithm.Ed25519)` round-trip;
fail-closed confirmed: wrong key → `BiscuitValidationError`, scope escape →
`AuthorizationError`, expired caveat vs host clock → `AuthorizationError`;
`UnverifiedBiscuit.revocation_ids` (list) / `block_source(index)` / `root_key_id()`
readable without authorization. All match the ADR's interface section.

## Scope notes

- The two advisory upgrades and the two npm lockfile repairs are trunk CI debt,
  not part of the #1838 decision deliverable; they are included because this is an
  explicit CI-repair round ordered to fix the named failing gates with local
  proof. No quality/*.json ledger, no ratchet authorization, and no gate script
  was edited; the pip-audit allowlist was NOT extended (both fixes have fixed
  versions, so the gate's own policy mandates upgrade over triage).
- The issue's owner-acceptance boundary is untouched: ADR-101826-2a63 remains
  `Proposed`, the decision gate remains open, `contracts:`/`tests:` stay empty.
  Nothing here resolves the decision or claims implementation.

## Residual risks

- The other three images (engine, engine-research, rsi-runner) were not rebuilt
  locally; they install from the same repaired `uv.lock` and contain no npm tree,
  and their build recipe is unchanged. Grype/SBOM/license legs of the containers
  job were not run locally (require the full four-image build).
- The original containers-job excerpt cannot be attributed to a single Dockerfile
  line from the log tail alone; the npm stage, the full hive image build, its
  identity smoke, and Trivy are each now proven green locally, and `npm ci`'s
  audit behavior is empirically exonerated under the pinned builder image.

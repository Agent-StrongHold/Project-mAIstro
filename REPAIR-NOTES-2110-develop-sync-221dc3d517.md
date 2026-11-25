# REPAIR-NOTES — #2110 develop sync to 221dc3d517 (round 10)

Lane: CR2110 · branch `fix/windows-bootstrap-prerequisite` · prior head
`11466f5120e4fc40a61cfc3417f28ebc7675f9cf` · new base
`221dc3d517e7580dc80859259cfdf15a2fd3ec9e` (origin/develop tip at dispatch).

The previous repair run died on a provider 404 immediately after starting the
`git merge` of the declared develop base, leaving four unresolved conflicts and
a `pyproject.toml` whose conflict markers broke TOML parsing (the driver's
`uv sync`/`ruff` pre-checks exited 2 with "missing comma between array
elements" — see the round's `check-*.log`). This round resolved every conflict
in place and committed the merge. No branch feature work was touched; the
Windows bootstrap execution-policy content (get.ps1, relaunch/policy harnesses,
run-wsl-detection-e2e.ps1, maistro-bootstrap tests, inventory/ac-state notes)
is intact in the merge result.

## Conflict resolutions

### Dockerfile / Dockerfile.research (`dockerclibuild` stage, RUN line)

- HEAD (branch): `go get "${X_NET_MODULE_UPGRADE}"` (ARG-driven exact pin,
  #2110 CI-repair round) — kept.
- develop: explicit `github.com/klauspost/compress@v1.20.2` beside the x/net
  pin — kept as belt-and-braces (v29.9.3 already vendors compress 1.20.2, so
  the pin is idempotent; it holds the vendored fix version against resolver
  drift).
- Resolved line (both files, stage comments updated to match):
  `go get "${X_NET_MODULE_UPGRADE}" github.com/klauspost/compress@v1.20.2 && go mod vendor && \`

### pyproject.toml (`[tool.uv] constraint-dependencies`)

- graphql-core: both sides raised the floor to `>=3.3.1`; kept the branch's
  bare pin (the shared comment above it already documents CVE-2026-119286 →
  3.3.1; develop's inline duplicate comment dropped).
- dnspython: kept the branch's single `>=2.9.2` pin; develop's older
  `>=2.9.0` row is superseded (strict superset, same advisory coverage in the
  branch's #2110-round comments).
- Four-advisories comment (oauthlib/pyasn1/pypdf/soupsieve) and the
  soupsieve/patchright/playwright block: took develop's canonical text
  (PR #2389 + CR1373 provenance, PEP-440 `4.0 == 4.0.0` note, #2356
  node-26.13.1-overlay follow-up) and develop's pin order, dropping the one
  duplicate `patchright>=1.64.4` row the conflict alignment produced.
- Net effect: 15 pins, strictly dominating both parents. The only textual
  drops are PEP-440-equal (`soupsieve>=4.0.0` ≡ `>=4.0`) and strictly-below
  (`dnspython>=2.9.0` < `>=2.9.2`).

### packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts

Both sides independently repaired the same flaky ladder test after the merge
base:

- branch (d3c793ae07, 11-16): restructured to overshoot-chunks + no-clock
  observation with `CLOCK_QUANTUM_ENVELOPE_MS = 1_100`;
- develop (8b6e4eca40 et al., 11-19/20): kept the poll-nudged shape and raised
  the budget to `BOUNDARY_SLOP = 2_500`, absorbing both the observed ~1s
  real-time drift (job 133112496460) and the +5ms quantum accumulation the
  branch's restructure addressed (45015 ≪ 47500 budget).

Resolution: took develop's ladder-test region verbatim (upstream's later rework
supersedes the branch's flake repair, and the 2.5s budget covers both observed
failure modes). The branch's *other* flake fix in the same file — the
banner-sync rewrite of the "success resets the cadence" test (CI run 43806818617,
job 133099866372) — is preserved and is compatible with develop's UI (it keys
on the poll banner, not the removed Dashboard page; the Dashboard→Home link
changes from #2460 are taken from develop as required for the spec to compile).

## Local validation (all run at the resolved merge state)

| Gate | Result |
|------|--------|
| `uv sync --locked --extra dev` | exit 0 (lock consistent with resolved pyproject) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3655 files already formatted |
| `uv run pytest tests/test_image_lock_contract.py -q` | 30 passed |
| `uv run pytest tests/test_dependency_namespaces.py tests/test_root_image_interpreter_lines.py tests/test_prepull_copy_sources.py tests/test_distribution_contract.py tests/test_check_image_inventory.py -q` | 124 passed |
| `uv run python scripts/check-suite-inventory.py` | ok — 21 suites match recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK (167 backlog items) |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `docker build --check -f Dockerfile .` / `-f Dockerfile.research .` | Check complete, no warnings found |
| esbuild transpile of rsi-polling-resilience.spec.ts | 0 errors |

No tests were added or removed by this round (test set identical to both
parents; the ladder test is the same single test either way), so no
inventory-note delta is required.

## Deeper verifier findings at the resolved merge state

| Gate (CI-exact) | Result |
|-----------------|--------|
| `tests/test_get_ps1_wsl_detection.py -q` (the PR's own static + PowerShell-mocked regressions; pwsh available here) | 28 passed |
| `packages/maistro-bootstrap/tests -q` | 274 passed, 5 skipped (pre-existing docker-gated skips) |
| `npm audit --json` (canvas frontend) + `python scripts/npm_audit_gate.py` | 0 advisories at every severity; gate OK — the previously documented red root cause (GHSA-fc5q-39xc-vjpf / picomatch) was withdrawn upstream 2026-11-18, and the new base judges this surface via the triaged ratchet (#2375) |
| `python scripts/check-test-duplicates.py` | ok — 0 byte-identical groups |
| CI-exact one-process suite: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60` | 11254 passed, 222 skipped, **2 failed** (see below) |

### Residual failure (branch-neutral, not repairable in this lane)

`tests/test_check_public_routes.py::TestTheRepositorysOwnRegistry` (2 tests)
fails because the `/v1/auth/register` and `/v1/setup/` temporary exemptions in
`quality/public-routes.json` carry `expires: 2026-11-24` and the gate ran on
2026-11-25. Evidence of branch-neutrality:

- `git diff 221dc3d517 HEAD -- quality/public-routes.json` is empty — the
  registry is byte-identical to the declared develop base; the gate's own
  ratchet line reports `12 public route identities -> 12 public route
  identities` (base == candidate surface).
- The expiry is time-based, so develop's own tip fails identically today.
- A re-justification already exists authored by the #2372 repair lane
  (commit `71db1c9109`, dated 2026-11-25) — it is NOT on origin/develop yet,
  so taking it here would jump another lane's writer boundary. Ledger edits
  are prohibited in this lane outside the vulture exception, and
  `quality/public-routes.json` is a policy ledger.

Disposition: hand off to the #2372 lane / next develop sync. Not a defect of
this merge.

### Local-only stale artifact removed

`quality/ac-state.json` existed on disk, untracked and git-ignored
(`.gitignore:88`); the tracked copy was deliberately deleted upstream by
`db442b5d15` (#604 folded the shared file into `quality/ac-state-notes/`).
`check-branch-independence.py` discovers on-disk files, so this stale debris
failed `test_every_quality_json_state_surface_is_classified_once` locally
(CI's fresh checkout never sees it). Moved to
`/tmp/stale-ac-state-json-backup-5f539347e3.json` (bytes preserved); the test
passes after the move.

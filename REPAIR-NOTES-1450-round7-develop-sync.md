# Repair notes — issue #1450 round 7 (develop sync to 809f84c8 + driver-gate revalidation)

Branch `auto-80`. Head before this round: `0551347450` (the round-6 merge of
develop `a660bc2a9d` plus the round-6 repair `5150c73df2`). This round merges
the one develop commit that landed after that merge and re-proves, locally
and from scratch, every gate named in the lane brief. Nothing here trusts a
prior round's claims; every number below was re-executed at this round's head.

## Develop sync

`origin/develop` advanced to `809f84c8a650` ("Build(deps-dev): update lizard
requirement from >=1.24.1 to >=1.25.0 (#2387)") — a one-line floor bump in
`requirements-dev-tools.txt`. Merged conflict-free into `auto-80` (merge
commit `67bbe996f8a2`); `git rev-parse origin/develop` and the lane-declared
develop base agree at `809f84c8a650`. No ledger rows touched; `git diff --stat
a660bc2a9d..809f84c8a6` is exactly `requirements-dev-tools.txt | 2 +-`.

## Salvage from the crashed prior attempt

The prior run died on a provider error mid-write and left three stray
untracked files at the worktree root (`<parameter>path`, `MAISTRO_RESULT`,
`result.json` — the crashed model's accidental output dump) plus an
uncommitted trailing-newline fix in `tests/test_devskim_scan_scope.py`.
The newline fix is committed here (ruff format requires it); the stray files
were relocated to the job directory (`salvaged-stray-files/`), not deleted.

## Gates re-run at this head (all re-executed, not assumed)

- `uv run ruff check .` → All checks passed.
- `uv run ruff format --check .` → 3573 files already formatted.
- Driver-exact `uv run pytest packages/maistro-bootstrap/tests/test_container_lane.py
  packages/maistro-bootstrap/tests/test_container_sandbox.py -q` → 18 passed,
  1 skipped (the by-design no-backend refusal skip).
- The round-6 failing driver gate, driver-exact:
  `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests` → **ok: 279 = 279** (was
  `expected 319, collected 279` at `abede31fb3`; fixed by the round-6
  phantom-delta correction note, which this run confirms is correct and
  sufficient).
- Full `uv run python scripts/check-suite-inventory.py` → ok: 21/21 suites
  match; 35492 collected node IDs, all unique; 0 duplicate evidence.
- Sandbox conformance/escape, real backends:
  `uv run pytest packages/maistro-core/tests/sandbox
  packages/maistro-core/tests/extensions/test_sandbox_conformance.py -q`
  → **258 passed, 38 skipped** (skips are the hardware/profile-gated live
  lanes, e.g. Kata live conformance without an evidenced Kata host).
- CI-exact vulture ratchet: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → RC 0,
  1236 reviewed identities = 1236 findings against base `809f84c8a650`.
- `uv run pytest tests/test_devskim_scan_scope.py -q` → 21 passed (the file
  this round touches only gained its missing final newline; node count
  unchanged, so no inventory-delta note is required or written).

## Acceptance anchor map (issue #80 criteria → reachable tests, verified live)

- Escape suite covers filesystem/process/namespace/device/host-socket/
  credential/privilege attacks: `packages/maistro-core/tests/sandbox/
  test_escape_conformance.py` (host passwd absence L185, home dirs L192,
  pid1 L223, PID namespace L234, nested userns L248, chroot refusal L271,
  mount refusal L278, block devices L293, virtualization device L302,
  device creation L309, unix sockets L319, container socket L328, listening
  ports L335, capabilities L369, setuid escalation L376).
- Network/credential default-deny: `test_network_default_deny.py`,
  `test_credential_boundary.py`,
  `test_the_environment_holds_only_what_the_config_put_there` (L347),
  `test_undeclared_egress_cannot_reach_the_network` (extensions
  test_sandbox_conformance.py L232), bootstrap
  `test_seed_leaves_ambient_credentials_on_the_host` (L181).
- No `.env`/`.git`/host secrets in seeded work: bootstrap
  `test_container_sandbox.py` seed denylist tests (L181, L247) plus the
  seed-symlink boundary test from round 5.
- Non-root: `test_lane_masks_securityfs_privately_and_drops_privileges`
  (test_container_lane.py L23); the CI `sandbox-conformance` lane asserts
  the non-root uid on the rootless daemon.
- Read-only-by-default writable scope: escape conformance L199 (runtime
  dirs read-only) and L209 (only writable host path is the workdir).
- Timeout/kill/cleanup + exhaustion: L83–L145 (memory/CPU/file-size/
  zero-budget), L415 (timeout leaves nothing running), L454 (setsid
  grandchild), L490 (destroy removes workdir).
- CI lane: `.github/workflows/ci.yml:747` `sandbox-conformance` (rootless
  daemon + fail-closed refusal proof under `uv run --extra bootstrap`,
  fixed in round 6).
- SECURITY.md cites the evidence: SECURITY.md L364–397 (SPEC-190 suite,
  Builder reconciliation onto the M2-B1 selector, matrix link).
- Production instantiation: escape conformance spawns the shipped
  `BubblewrapSandboxBackend` (the M2-B1 Tier-3 backend), not a hardened
  fixture; bootstrap tests instantiate the production
  `ContainerBuilderSandbox` adapter; Kata live conformance uses the
  production selector + policy.

## Residual risks

- The 38 sandbox skips are the hardware/profile-gated live lanes; they are
  by design (documented in SECURITY.md and the support matrix) and green CI
  covers the container lane on the rootless runner.
- CI's last merge-queue evaluation reported green; this head adds only the
  develop lizard floor bump (validated on develop's own CI), a newline, and
  this note.

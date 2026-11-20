---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 16 (independent review) — develop-sync head `cea534a80`

Re-review after the develop merge `9556a157b` into `auto-80`. All checks below
were executed by this reviewer at exactly
`cea534a8026120190191a0549179c588c2d29a87` on a clean tree; the only delta this
record adds is itself (docs-only).

## Develop-merge drift check

`git diff --stat 04c679246..cea534a80` over `packages/maistro-bootstrap`,
`packages/maistro-rsi`, `packages/maistro-core/tests/sandbox`, `SECURITY.md`,
`.github/workflows/{ci,quality,vulture-ratchet}.yml`, `docs/specs`, `docs/adr`
is **empty**: the merge brought only foreign-lane commits `9556a157b` (refuse
parent completion over paused human NodeRun) and `59f949313` (synthetic git-SHA
fixture marking). No #80 surface drift. Round-14/15 verification records
`66dee91` and `04c679246` remain ancestors of this head.

## Re-executed at this head (not assumed)

- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q` →
  **33 passed** (Docker 29.7.2 live).
- `uv run pytest packages/maistro-core/tests/sandbox -q -rs` →
  **113 passed, 35 skipped**; every skip is fail-closed with reason "bubblewrap
  cannot build an isolated namespace here" (host userns restriction); the CI
  lane (`ci.yml:435-452`) installs bubblewrap and relaxes
  `apparmor_restrict_unprivileged_userns` so kernel assertions execute.
- `uv run ruff check .` → all checks passed.
- Vulture ledger, CI form (`--exclude '*/third_party/*'`, as invoked at
  `quality.yml:836-843` and `vulture-ratchet.yml:80-86`) → **exit 0**
  (1404 == 1404, base `9556a157bb56`, candidate `cea534a80261`). The
  exclude-less form still exits 1 but is run by no gate.
- `scripts/check-security-inventory.py` → exit 0 (60 cited paths, 23 rows).
- Suite inventories `check-suite-inventory.py` for `maistro-bootstrap/tests`
  (249) and `maistro-rsi/tests` (793) → ok (driver logs, this job).

## Acceptance re-derivation (spot-read at this head)

- Network default-deny: `test_agent_commands_cannot_reach_any_network_by_default`
  asserts live `docker inspect …NetworkMode == "none"` plus per-host egress
  probes (v4/v6/metadata/private + DNS) with explicit "was not probed" guards.
- Credential default-deny + seed hygiene:
  `test_container_environment_is_credential_default_deny`,
  `test_seed_leaves_ambient_credentials_on_the_host` (indexed `.env*` under a
  split index, untracked secrets, `.pem` at depth) and the hardening
  denylist/allowlist tests.
- Non-root: `test_agent_execs_run_as_unprivileged_user` (pinned uid, `/etc`
  write and `chown` refused) + `test_the_only_root_exec_is_the_pre_seed_chown`.
- Read-only scope: `test_rootfs_and_writable_scope_are_explicit` (live inspect
  `ReadonlyRootfs`, `/proc/mounts` enumeration, `/dev/shm`+`/dev/mqueue` RO).
- Timeout/kill/cleanup/exhaustion: detached-descendant kill, context cleanup,
  memory containment, failed-enter/seed-failure cleanup — all in the 33-pass
  run.
- Production parity: the suite imports `ContainerBuilderSandbox` +
  `DEFAULT_IMAGE` (`maistro-builders:latest`) from the production module;
  production caller `local_loop.py:804-806` uses the same class; CI
  (`ci.yml:466-474`) builds the same image from a tests-only context.
- SECURITY.md:326-339 cites both real-backend conformance suites; the security
  inventory gate passes.

## Live PR #1450 refresh at this head

`gh pr view 1450` — `headRefOid` equals `cea534a8026…`; body unchanged
("Refs #80", no closure keywords); no `fixes/closes/resolves` issue refs in any
branch commit message (only prose "resolves membership" in `3691b8edb`).
Rollup: `exact-debt-ledger` (Vulture Ratchet), SAST, supply-chain, Gate C,
Cage Guard, DevSkim, ADR front-matter **SUCCESS**; CI `test`,
`lint-and-type-check`, conformance and coverage jobs IN_PROGRESS/QUEUED at
review time — GitHub-side execution of those remains **UNVERIFIED by policy**;
each command they run was proven green locally at the exact head above.

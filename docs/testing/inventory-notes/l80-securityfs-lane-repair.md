---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---

# Issue #80 — private securityfs setup for the rootless conformance lane

Scope: repair at `d4b3c7919c5e48d68901c3c9493c9fd0382fe67e`, not a
new isolation backend. Initial worktree was clean; an empty incoming patch was
preserved. No uncommitted work was discarded. This job had no driver check logs.

## Evidence and repair

The previous verifier recorded container creation failing with `Could not check
if docker-default AppArmor profile was loaded: open
/sys/kernel/security/apparmor/profiles: permission denied`. Image loading itself
succeeded; the enforcement probe failed and the escape suite never ran remotely.

The CI-only wrapper `scripts/ci-rootless-mountns.sh` creates a private mount
namespace, covers securityfs with a read-only empty tmpfs, then drops to the
original non-root uid/gid before executing rootless Docker. It does not unmount
host securityfs, disable host AppArmor, add `apparmor=unconfined` to sandbox
containers, or change production launch flags. The same production
`ContainerBuilderSandbox` and escape assertions remain load-bearing. The
wrapper's privileged operations are provisioning, never candidate execution.

New live test `test_container_lane.py` models a visible AppArmor directory with
unreadable profiles in an outer private mount namespace, verifies the read
actually fails as the lane user, executes the actual CI wrapper, and proves:
securityfs discovery is absent and read-only inside, uid/gid are restored,
effective capabilities are empty, and caller/host mounts are unchanged. CI runs
this opt-in test before daemon launch; ordinary developer runs explicitly skip
it unless `MAISTRO_TEST_ROOTLESS_LANE=1` is set.

The existing live credential-deny test previously checked absence without
populating credentials. It now injects four sentinel host credential variables
and all five Docker client proxy fields before entering the production sandbox;
none may reach candidate code. This strengthens an existing node, not the count.

ADR reconciliation: accepted ADR-093 Decisions 2, 5 and 6 govern this
transitional supervised Tier-3 lane. Proposed SPEC-190 does not justify claiming
VM containment for a Docker backend. Neither AppArmor nor hostile-kernel
containment is proven by a lane with securityfs masked. Execution authority
(`Goal -> Graph -> Run -> NodeRun -> Attempt`) is unchanged.

## Validation

- Live provisioning regression: **1 passed** (passwordless sudo, real namespaces).
- Exact vulture CI command: **passed**, 1403 reviewed identities / 1403 findings,
  zero unclassified identities. No source identities changed, so no evidence
  supports a ledger amendment.
- Foreground-owned local daemon using the actual wrapper, Docker **28.5.2**,
  rootless extras **29.8.1**, vfs and workflow network flags: **16 passed,
  1 expected inverse-posture skip**. `memory.max=67108864` under the 64m probe;
  `SecurityOptions` includes rootless and seccomp, systemd cgroup v2. No leftover
  containers; owned daemon shut down cleanly. This is local execution, not a
  remote GitHub runner claim.
- First local daemon attempt failed because this harness PATH lacked `/usr/sbin`
  (`sysctl` missing); adding the system sbin paths fixed the validation setup.
- shellcheck 0.10.0 on the new wrapper and actionlint 1.7.7 with shellcheck on
  `.github/workflows/ci.yml`: **passed**.
- Repeated the full foreground-owned daemon validation after strengthening the
  credential/proxy test: **16 passed, 1 expected inverse-posture skip**, same
  enforced memory limit and clean shutdown. Log:
  `/home/dev/maistro/jobs/1a7addef87bf497386cee334ccb0a72a/real-conformance-final.log`.
- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q`: **250 passed, 17 skipped** (16 full
  escape tests deliberately refuse this daemon posture; one existing
  non-container optional test skips). Includes live rootful refusal and the
  provisioning regression.
- `uv run pytest packages/maistro-rsi/tests -x -q`: **801 passed** (7 existing
  Pydantic deprecation warnings). No RSI implementation changes this round.
- `uv run ruff check .` and `uv run ruff format --check .`: **passed**,
  2602 files formatted. Initial C420 in the strengthened proxy fixture was
  corrected with `dict.fromkeys` before rerunning.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **267, matches**.
- `check-workflow-write-safety.py`, `check-required-checks.py`,
  `check-security-inventory.py`, `check-doc-links.py`: **passed**.
- Final exact vulture command repeated: **passed**, unchanged 1403 identities.
  `git diff --check`: **passed**.
- Explicit rootful-refusal test + hardening module: **27 passed**.
  RSI suite inventory: **801, matches**. `check-ac-state.py` report-only mode
  exited 0 (not proof of acceptance; `--run-tests` was not requested).

## Acceptance mapping

- Filesystem, process, namespace/kernel-surface, network, device, host socket,
  credential and privilege classes: all 16 production-backend escape tests
  executed on the privately provisioned rootless daemon. This is Tier-3 surface
  conformance, not proof against kernel exploits.
- Network/credential default deny: egress tests passed; deliberately populated
  host credential environment and Docker proxy configuration did not cross.
- `.env`, `.git`, unrelated host secrets: live tracked/untracked seed test passed.
- Non-root candidate execution: live uid/capability/uid-map tests passed;
  rootful unmapped daemon refused. Only trusted pre-seed workspace chown is root.
- Writable scope: read-only rootfs and runtime tmpfs/live mount write probes passed.
- Timeout, detached-process kill, cleanup and exhaustion: live tests passed;
  independent 64m cgroup probe returned 67108864 bytes, no leftover containers.
- CI/designated lane: recipe and namespace regression executed locally; hosted
  CI execution remains **UNVERIFIED**, so no integration approval is claimed.
- SECURITY.md evidence: cites this record and explicitly disclaims successful
  remote execution and AppArmor containment.
- Same production backend: escape tests import and instantiate the unchanged
  `maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`.

Remote CI remains UNVERIFIED; no push or GitHub mutation is permitted in this
repair round. SECURITY.md and the support matrix now distinguish lane
configuration from successful remote execution instead of repeating the prior
unsupported claim.

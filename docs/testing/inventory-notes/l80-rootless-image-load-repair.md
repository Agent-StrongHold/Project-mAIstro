---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 — independent revalidation of the reported image-load blocker

Starting HEAD: `c121f91407f95e45c0c1169567ba6f9ef1f5182b`; clean assigned
worktree `/home/dev/Git/wt/auto-80`. Only issue #80 is processed. No driver
`check-*.log` files were present in job
`f10453b1466e4930ad681bb22bd63d8c` at the initial snapshot. This record adds no
tests and changes no production code, workflow, grant, or debt identity.

## Actual evidence, not the failed step's name

Read-only retrieval of the assigned CI job's logs:

`gh api repos/Agent-StrongHold/Project-mAIstro/actions/jobs/108713321959/logs`

The saved `prior-ci-job.log` shows:

- Line 1372: `Loaded image: maistro-builders:latest`.
- Line 1373: `Could not check if docker-default AppArmor profile was loaded:
  open /sys/kernel/security/apparmor/profiles: permission denied`.
- Line 1376: the subsequent container probe exited **126**.

Thus the reported image-load step failure was not an image-transfer failure.
The assigned starting commit already contains the targeted private-securityfs
provisioning repair and its real namespace regression. See
[l80-securityfs-lane-repair.md](l80-securityfs-lane-repair.md). Both SECURITY.md
and the support matrix already distinguish configured CI from successful hosted
execution. Further image-transfer changes would not address this evidence.
No push, dispatch, GitHub mutation, or background command is authorized or used.

## Independent validation in this round

Logs are under `/home/dev/maistro/jobs/f10453b1466e4930ad681bb22bd63d8c/`.

- Exact requested vulture gate: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**,
  1403 reviewed identities / 1403 findings, zero unclassified. No identities
  were added or removed; amending the ledger without any identity delta would
  manufacture a change, not repair a gate.
- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped**.
  All 18 qualifying-daemon production conformance cases and the real private
  namespace provisioning regression ran. Skips: the inverse rootful-daemon
  refusal case and an existing Windows-only test. The pre-existing rootless
  daemon reports seccomp, rootless, cgroup v2 and systemd; this is not a fresh
  hosted-runner provisioning claim.
- Independent rootful refusal: `DOCKER_HOST=unix:///var/run/docker.sock uv run
  pytest packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -x -q -rs`: **1 passed**, including no leftover sandbox container.
- The workflow's independent cgroup probe, `DOCKER_HOST=unix:///run/user/1000/docker.sock
  docker run --rm --network=none --memory=64m --memory-swap=64m
  maistro-builders:latest cat /sys/fs/cgroup/memory.max`, returned **67108864**.
- `uv run pytest packages/maistro-rsi/tests -x -q`: **801 passed**, seven
  existing Pydantic deprecation warnings; includes the autonomous mode-floor
  CLI/library/factory refusal and parity tests.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`:
  **passed**, 2602 files.
- Actual CI mypy source-tree invocation (`uv run mypy` with maistro-core,
  maistro-server, maistro-turing, maistro-canvas, maistro-bootstrap,
  maistro-registry, maistro-evolve, maistro-rsi and maistro-design `src`
  directories): **passed**, 845 files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **275, matches**.
- `uv run python scripts/<gate>`: **passed** for `check-merge-markers.py`,
  `check-build-context.py`, `check-security-inventory.py`,
  `check-workflow-write-safety.py`, `check-required-checks.py`,
  `check-doc-links.py` and `check-promotion-surface.py`.
- `git diff --check`: **passed**.

## Architectural reconciliation

Accepted ADR-093 Decisions 2, 5 and 6 govern this transitional supervised Tier-3
backend. Proposed SPEC-190 does not turn these shared-kernel surface tests into
VM containment evidence. Masking securityfs in the daemon's private namespace
is provisioning, not an alternative sandbox or authorization path; it proves
neither AppArmor confinement nor resistance to hostile kernel exploits.
`Goal -> Graph -> Run -> NodeRun -> Attempt` is unchanged.

## Acceptance and handoff

| Criterion | Executed evidence |
|---|---|
| Filesystem, process, namespace/kernel surface, network, devices, host sockets, credentials and privilege | All 18 real production-backend conformance cases passed; Tier-3 surface only, not kernel-exploit containment. |
| Network/credential default deny | Live egress and populated host credential/Docker proxy tests passed. |
| Seed excludes `.env`, `.git`, unrelated secrets | Live seed test and both replacement-path refusal regressions passed. |
| Non-root candidate | Live uid, uid-map, capabilities and no-new-privileges assertions passed; independent rootful refusal passed. Trusted pre-seed workspace chown is the sole root bootstrap. |
| Read-only default, explicit workspace/scratch writes | Live rootfs configuration and mount-by-mount write probes passed. |
| Timeout, kill, cleanup, exhaustion | Live detached-descendant timeout, removal and over-budget allocation tests passed; independent 64 MiB cgroup probe enforced 67108864 bytes. |
| CI/designated conformance lane runs suite | Local production suite and actual CI wrapper regression passed; successful hosted execution remains **UNVERIFIED**. |
| SECURITY.md cites real evidence | Existing limitation #8 cites the private-securityfs and seed-path validation records and explicitly retains the hosted limitation. |
| Same supported production backend | Tests directly instantiate `maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`; no separately hardened fixture. |

Outstanding requirement: an authorized hosted run of the existing repaired lane
on the candidate commit. The cited failing job predates the private-securityfs
repair; its failure does not justify another speculative implementation change.
This round cannot certify hosted execution without that run. Status: **BLOCKED**,
not integration approval. Checked 1 issue, implementation changes needed 0,
skipped issues 0; next: authorized hosted conformance verification.

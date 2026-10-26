---
inventory-delta:
  packages/maistro-bootstrap/tests: +8
---

# Issue #80 — indexed seed paths cannot authorize unrelated host contents

Starting HEAD: `e4903977f56d108754d3bbbd6aa8f6a49bd0c271`. This repair
inherited the two parametrized regression tests and this note uncommitted;
they were preserved before editing in `../incoming-80-fb9d30.patch` and the job's
`incoming-inventory.md`. Only issue #80 is processed. No driver `check-*.log`
files were present in job `fb9d30ae1e6b4cdc8886b1bdf9a3bd67` at the initial snapshot.

## Reproduced production failures

Against the existing rootless Docker daemon, the unchanged production
`ContainerBuilderSandbox` admitted both of these host fixtures:

- An indexed file replaced with a directory: tar recursively included its
  untracked `unrelated-host-secret.txt`.
- An indexed parent directory replaced with a symlink to an external directory:
  tar followed that intermediate component and included the external
  `config.txt`, despite that file never having been indexed.

Both files were readable inside the sandbox with the exact value
`l80-secret-sentinel`. The original seed suite missed these worktree type changes.

This round independently reproduced both refusals failing in the real-Git
unit tests and against the existing rootless daemon before repair (two failures
each, recorded in `check-seed-before.log` and `check-live-seed-before.log`).

Two parametrized live tests and three real-Git unit cases pin refusal of these
inputs and a FIFO replacing a tracked file. Three further real-Git cases prove
unstaged leaf/parent deletion is omitted and a dangling leaf symlink remains a
link. The flag-construction test additionally requires nonrecursive tar.
Production now checks ancestor directories with `lstat`, accepts only regular
files or symlink leaves, and disables tar recursion as a second layer.

Initial repaired validation: full live conformance plus hardening **46 passed,
1 inverse-posture skip**; independent rootful refusal **1 passed**. Vulture
**passed** (1403 reviewed identities / 1403 findings, zero unclassified), so no
ledger amendment is justified. Initial lint found SIM117 in the inherited live
test; combined its context managers. Full validation is recorded below.

## Architecture and limits

ADR-093 Decisions 2, 5 and 6 govern this transitional supervised Tier-3 backend;
SPEC-190 is Proposed and does not grant it VM/hostile-kernel containment.
No execution authority, scheduler, authorization path or isolation tier changes.
The host worktree must remain stable while the trusted host prepares the seed;
this change does not claim protection against concurrent host-side mutation.

## Final validation for this repair

Logs: `/home/dev/maistro/jobs/fb9d30ae1e6b4cdc8886b1bdf9a3bd67/`.
No GitHub mutations or background commands were performed.

- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped**.
  Skips are the inverse rootful-posture case and an existing Windows-only test.
  All 18 qualifying-daemon conformance nodes and the private-securityfs
  provisioning regression executed, not skipped. This used the pre-existing
  rootless daemon; it does not certify fresh hosted-runner provisioning.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -x -q -rs`: **1 passed**, including no leftover container.
- Rootless Docker **29.7.2**, systemd cgroup **v2**, rootless/seccomp security
  options; independent `docker run --rm --network=none --memory=64m
  --memory-swap=64m maistro-builders:latest cat /sys/fs/cgroup/memory.max`
  returned **67108864**, proving the daemon enforces memory limits.
- `uv run pytest packages/maistro-rsi/tests -x -q`: **801 passed**, seven
  existing Pydantic deprecation warnings. Includes CLI, library and factory
  autonomous-mode floor refusal; no RSI code was changed in this round.
- `uv run ruff check .`: **passed** after fixing inherited SIM117.
- `uv run ruff format --check .`: **passed**, 2602 files.
- Standalone `uv run mypy packages/maistro-bootstrap/src` initially failed
  with five cross-package import typing errors in `responses_callable.py` and
  `model_selector.py` (neither changed). Re-running the actual CI invocation,
  `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src
  packages/maistro-evolve/src packages/maistro-rsi/src packages/maistro-design/src`,
  **passed**: shared source trees must be explicit for this workspace's mypy.
- Final `git diff --check` and doc-link gate after documentation updates:
  **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **275, matches** (+8 in this note).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed** before and after
  source repair, 1403 reviewed identities / 1403 findings. No unbanked or removed
  identities; leave the exact-debt ledger unchanged rather than manufacture debt.
- `uv run python scripts/<gate>`: **passed** for `check-merge-markers.py`,
  `check-build-context.py`, `check-security-inventory.py`,
  `check-workflow-write-safety.py`, `check-required-checks.py`,
  `check-doc-links.py`, and `check-promotion-surface.py`.

## Acceptance mapping and outstanding blocker

| Criterion | Executed evidence |
|---|---|
| Filesystem, process, namespace/kernel surface, network, device, host socket, credential and privilege attacks | All 18 live production-backend conformance nodes passed on the qualifying rootless daemon. Namespace probes test the Tier-3 surface, not resistance to kernel exploits. |
| Network/credential default deny | Real egress probes and populated host credential/Docker proxy sentinel tests passed. |
| No `.env`, `.git`, unrelated secrets in seed | Existing live seed test passed; both new replacement-path refusal tests changed from red to green. |
| Candidate not container root | Live uid, capability and uid-map tests passed; rootful daemon independently refused. Only trusted pre-seed workspace chown runs as container root. |
| Read-only default; explicit scratch/workspace writes | Live read-only configuration and mount-by-mount write probes passed. |
| Timeout, kill, cleanup, exhaustion | Detached-descendant timeout, context cleanup and allocation-over-budget tests passed; independent cgroup limit probe enforced 64 MiB. |
| CI/designated conformance lane runs suite | Local rootless suite and actual CI private-mount wrapper regression passed. Successful **hosted lane execution remains UNVERIFIED**; do not turn a local run into a claim that CI completed. |
| SECURITY.md cites real evidence | SECURITY.md and the support matrix now link this record as well as the provisioning repair, explicitly retaining the remote limitation. |
| Same production backend, not hardened fixture | Tests import and instantiate `maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`, including the repaired host-side seeding path. |

The inherited provider-error interruption is salvaged and the seed leak is
repaired. No new evidence of a CI code defect justifies speculative workflow
changes. A permitted remote run of the existing lane on the final commit is
still needed to resolve the previous remote-execution blocker; no push or
workflow dispatch is authorized here. Status: checked 1 issue, repair done 1,
skipped 0, implementation errors 0; next: hosted conformance verification.

---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 — current-candidate validation and remote availability blocker

Assigned starting HEAD: `db437a2eadb3f778e11e00e701d8421d903ed209`, verified
clean in `/home/dev/Git/wt/auto-80`. This round processes only issue #80 and
adds this evidence record; no production, workflow, test, or ledger changes
are justified by the executed checks. Test inventory is unchanged.

## Evidence behind the inherited finding

The previous job's saved `prior-ci-job.log`, lines 1372–1376, records
`Loaded image: maistro-builders:latest`, followed by failure to read
`/sys/kernel/security/apparmor/profiles` and exit 126. The failed step's name
was not evidence of a failed image transfer. The assigned HEAD already has
`scripts/ci-rootless-mountns.sh` and its live namespace regression addressing
that failure. SECURITY.md and the support matrix already explicitly label
hosted Builder execution unverified; they no longer claim successful hosted
execution. Neither merits a speculative additional repair.

A read-only request for **this exact assigned HEAD** was executed:

```text
gh api repos/Agent-StrongHold/Project-mAIstro/commits/db437a2eadb3f778e11e00e701d8421d903ed209/check-runs
```

Result: **HTTP 422, No commit found for SHA**. The local ref resolves, but the
remote ref was not found; further remote inspection was skipped. No alternate
refs were guessed and no push, dispatch, or other GitHub mutation was attempted.
Consequently this worker cannot verify a hosted run of the repaired candidate.
The remaining blocker requires an authorized campaign owner, not another
unsubstantiated change to image transfer or sandbox flags.

## Fresh executed validation

Logs are in job directory
`/home/dev/maistro/jobs/9277b908897f47b7a775197db33cdefc/`.
No driver `check-*.log` files existed there at the initial snapshot; previous
job logs were inspected, and the following results were independently rerun.

- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped**.
  All 18 real qualifying-daemon conformance cases and the real CI provisioning
  namespace regression executed. Only the Windows-specific case and inverse
  rootful refusal case skipped. The pre-existing rootless daemon reports
  seccomp, rootless, cgroup v2, and systemd; this is not a claim of a fresh
  hosted daemon startup.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -x -q -rs`: **1 passed**. Rootful daemon reports no rootless option.
- `DOCKER_HOST=unix:///run/user/1000/docker.sock docker run --rm
  --network=none --memory=64m --memory-swap=64m maistro-builders:latest
  cat /sys/fs/cgroup/memory.max`: **67108864**, enforcing the independent
  workflow memory-budget probe.
- `uv run pytest packages/maistro-rsi/tests -x -q`: **801 passed**, seven
  existing Pydantic deprecation warnings; includes autonomous mode-floor guards.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1403 reviewed
  identities / 1403 findings, zero unclassified. There are no unbanked or
  eliminated identities to amend; manufacturing a ledger change would not
  repair this passing gate.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 2602 files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **275, matches**.
- `uv run python scripts/<gate>`: **passed** for `check-merge-markers.py`,
  `check-build-context.py`, `check-security-inventory.py`,
  `check-workflow-write-safety.py`, and `check-required-checks.py`.

## Acceptance evidence and limits

| Criterion | Executed evidence |
|---|---|
| Filesystem, process, namespace/kernel surface, network, device, host socket, credential, privilege attacks | All 18 live production-backend cases passed; shared-kernel surface checks, not kernel-exploit containment. |
| Network/credential default deny | Live public/private/metadata/DNS egress attempts and populated host credential/Docker proxy regressions passed. |
| No `.env`, `.git`, unrelated host secrets in seed | Live indexed/untracked credential exclusion, gitlink exclusion, and both replacement-path refusal cases passed. |
| Candidate is not container root | Live uid/capability/no-new-privileges and uid-map assertions passed; independent rootful refusal passed. Only trusted empty-workspace ownership bootstrap uses uid 0 before seeding. |
| Read-only default with explicit scratch/workspace writes | Live rootfs configuration and mount-by-mount write probes passed, including read-only `/dev/shm` and `/dev/mqueue`. |
| Timeout/kill/cleanup/resource exhaustion | Live detached-descendant timeout, container removal, and over-budget allocation tests passed; independent cgroup probe enforced 64 MiB. |
| CI/designated lane runs suite | Existing lane is configured and its namespace regression passed locally. Hosted current-candidate execution remains **UNVERIFIED**; GitHub does not have the assigned HEAD. |
| SECURITY.md can cite real evidence | Limitation 8 cites the production suite and existing live validation records while explicitly retaining hosted and Tier-3 limitations. |
| Same production backend, not hardened test substitute | Tests instantiate `maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`, also used by production `maistro_rsi.contained_validation`; no alternate hardened fixture. |

Accepted ADR-093 Decisions 2, 5, and 6 govern the transitional supervised
Tier-3 backend. Proposed SPEC-190 cannot turn this evidence into a Tier-1/2
containment claim. The securityfs wrapper is host provisioning, not a new
execution or authorization path; it does not establish AppArmor confinement.
`Goal -> Graph -> Run -> NodeRun -> Attempt` is unchanged. Seed preparation
still assumes a stable trusted host worktree.

**Handoff: BLOCKED**, not integration approval. Checked 1 issue, local validation
completed, no implementation defect reproduced, no issue skipped; remote
validation unavailable. Next: authorized publication and hosted conformance
execution of the repaired candidate, then inspect its actual results.

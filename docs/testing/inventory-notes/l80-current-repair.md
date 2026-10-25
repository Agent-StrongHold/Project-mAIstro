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

## Follow-up repair job 9458faa2 — independently rerun, still blocked

Exact assigned starting HEAD: `ac0497aa05d1634cdbd59b7795912a87ece5226b`,
clean on `auto-80`. Scope frozen to issue #80; no incoming edits were discarded.
The job directory contained no driver `check-*.log` files. Fresh logs are under
`/home/dev/maistro/jobs/9458faa2d88746c185f294add7019bff/worker-*.log`.
This follow-up changes only this evidence note (inventory delta remains zero).

The previous block was checked against the exact assigned candidate, not a
substituted remote branch:

```text
gh api repos/Agent-StrongHold/Project-mAIstro/commits/ac0497aa05d1634cdbd59b7795912a87ece5226b/check-runs
HTTP 422: No commit found for SHA
```

Remote ref **not found; skipped** further remote inspection. Publishing or
triggering hosted validation is outside this worker's authority. The inherited
image-load/AppArmor failure is already addressed by the committed private
mount-namespace wrapper; its regression executed successfully below. No new
implementation failure justified changing that repair or the sandbox flags.

Fresh commands and outcomes:

- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped**.
  All 18 real qualifying-daemon conformance cases and the private namespace
  provisioning regression ran. Skips were Windows-only behavior and the
  inverse rootful refusal case. Docker independently reported rootless,
  seccomp, cgroup v2 and systemd; an existing daemon was used, not a freshly
  provisioned hosted runner.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -x -q -rs`: **1 passed**; this daemon independently reported no rootless
  security option.
- `DOCKER_HOST=unix:///run/user/1000/docker.sock docker run --rm
  --network=none --memory=64m --memory-swap=64m maistro-builders:latest
  cat /sys/fs/cgroup/memory.max`: **67108864**.
- `uv run pytest packages/maistro-rsi/tests -x -q`: **801 passed**, seven
  existing Pydantic deprecation warnings.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1403 reviewed
  identities / 1403 findings, **zero unclassified**. No unbanked or eliminated
  identity requires a ledger amendment in this CI-repair round.
- `uv run ruff check .` and `uv run ruff format --check .`: **passed**,
  2602 files formatted.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **275, matches**.
- `uv run python scripts/<gate>`: **passed** for `check-merge-markers.py`,
  `check-build-context.py`, `check-security-inventory.py`,
  `check-workflow-write-safety.py`, and `check-required-checks.py`.

The acceptance table above is re-proven locally by these executions: all eight
attack surfaces, network/credential default deny, seed exclusions and unsafe
replacement refusal, non-root candidate execution, read-only write scope,
timeout/detached-process kill, cleanup and memory exhaustion. Tests instantiate
the production `ContainerBuilderSandbox` imported by
`maistro_rsi.contained_validation` (lines 73–81), not a separately hardened
fixture. SECURITY.md limitation 8 and the support matrix accurately retain
both hosted-execution and shared-kernel limitations. ADR-093's supervised
Tier-3 allowance does not establish hardware/kernel-exploit containment;
SPEC-190 remains proposed. No execution authority or canonical lifecycle was
changed.

**Remaining acceptance: hosted conformance lane execution UNVERIFIED.** The
suite is configured in `.github/workflows/ci.yml:615–616`, but this candidate
is unavailable remotely. Local success cannot prove a hosted run. Handoff
remains **BLOCKED**: checked 1, done 0 (acceptance incomplete), skipped 0 issues,
errors 1 (exact remote ref lookup); next is authorized publication and hosted
validation, not another speculative code repair.

## Follow-up repair job 9df5bbdc — current head revalidated

Starting HEAD `50259c3152ff034cdaef43bda64ca0a3eb37ec8a` was verified clean
in the assigned `auto-80` worktree. Scope remained issue #80 plus the expressly
requested vulture gate. No driver `check-*.log` files existed at the initial
snapshot. Fresh command logs are in
`/home/dev/maistro/jobs/9df5bbdcba964b06847a1b02e84fa435/check-*.log`.
Only this evidence record changes; no tests, runtime, workflow, or ledger
identities changed, and the inventory delta remains zero.

Executed independently rather than relying on prior verification:

- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000
  DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped**.
  All 18 qualifying-daemon production conformance cases and the actual CI
  private-namespace provisioning regression ran. Only Windows-specific behavior
  and the inverse rootful refusal test skipped. The existing local daemon
  reported rootless, built-in seccomp, cgroup v2 and systemd; this does not
  establish fresh hosted-runner provisioning.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -x -q -rs`: **1 passed**, including cleanup on refusal.
- `DOCKER_HOST=unix:///run/user/1000/docker.sock docker run --rm
  --network=none --memory=64m --memory-swap=64m maistro-builders:latest
  cat /sys/fs/cgroup/memory.max`: **67108864**.
- `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py
  -x -q`: **15 passed**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1403 reviewed
  identities / 1403 findings, **zero unclassified**. There is no evidenced
  identity delta to amend; no speculative ledger change was made.
- `uv run ruff check .` and `uv run ruff format --check .`: **passed**,
  2602 files formatted.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`: **275, matches**.
- `uv run python scripts/<gate>.py`: **passed** for `check-merge-markers`,
  `check-build-context`, `check-security-inventory`,
  `check-workflow-write-safety`, `check-required-checks`, and `check-doc-links`.

The production class and adjacent tests were inspected before this note.
The acceptance table above is supported by the fresh live tests: filesystem,
process, namespace/kernel surface, network, devices, sockets, credentials and
privilege; network/credential default deny; `.env`/`.git`/unrelated-secret seed
exclusion; non-root candidate execution; read-only scope; timeout, detached
process kill, cleanup and memory exhaustion. Tests directly instantiate the
same `ContainerBuilderSandbox` imported by the production contained-validation
path, not an independently hardened fixture. SECURITY.md limitation 8 and the
support matrix already cite real evidence and explicitly retain hosted and
shared-kernel limitations. Accepted ADR-093's supervised Tier-3 allowance, not
proposed SPEC-190's eventual VM goal, bounds this evidence. No canonical
execution or authorization path changed.

The exact candidate's read-only remote lookup was executed once:

```text
gh api repos/Agent-StrongHold/Project-mAIstro/commits/50259c3152ff034cdaef43bda64ca0a3eb37ec8a/check-runs
HTTP 422: No commit found for SHA
```

Remote ref **not found; skipped** further remote inspection. Hosted current-head
conformance execution remains **UNVERIFIED**. The existing private-securityfs
repair and its passing local regression do not prove a successful hosted run.
No push, dispatch, or other GitHub mutation was attempted. Handoff remains
**BLOCKED**: checked 1, done 0 (acceptance incomplete), skipped 0 issues,
errors 1 (remote lookup). Next: an authorized owner must publish the candidate
and obtain hosted conformance results; another speculative sandbox or image-load
edit would not resolve the demonstrated blocker.

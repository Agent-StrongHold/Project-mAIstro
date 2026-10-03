---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 repair checkpoint

## Frozen scope

- Issue: #80 only; assigned worktree `/home/dev/Git/wt/auto-80`, branch `auto-80`.
- Starting HEAD verified: `ab1a30bf0ad545e12b0b53005383f68b37cbbb76`; clean worktree.
- Repair targets: `.github/workflows/ci.yml`, `scripts/ci-rootless-mountns.sh`, adjacent Builder sandbox production/tests and security evidence documentation only if actual findings require changes; `quality/vulture-baseline.json` only for the explicitly authorized exact-debt-ledger repair.
- No driver `check-*.log` files exist in the assigned job directory at initial inspection.
- Previous result artifact and ADR-093/SPEC-190 are the fixed investigation inputs. No GitHub mutations or broad develop sync planned (no conflict exists).
- Ambiguity: the supplied develop base is ahead/divergent across unrelated packages; those differences are not this repair's scope. Compare this repair to its starting HEAD.

## Progress

- ADR-093 Decisions 2, 5 and 6 bound this to the transitional supervised Tier-3 contract; proposed SPEC-190 does not establish VM containment. Canonical execution authority remains unchanged.
- Inspected the production `ContainerBuilderSandbox`, its live conformance tests and namespace provisioning test, the CI lane, production contained-validation caller, SECURITY.md limitation 8 and the support matrix. The inherited image-load/AppArmor failure already has a private-securityfs namespace repair and live regression. Security docs already explicitly retain hosted-execution limitations. No speculative additional repair is justified.
- Exact-debt-ledger command passed: 1403 reviewed identities / 1403 findings, zero unclassified. No ledger identity amendment is warranted.
- Rootful daemon reports seccomp/cgroupns, cgroup v2/cgroupfs; existing rootless daemon at `/run/user/1000/docker.sock` reports seccomp/rootless/cgroupns, cgroup v2/systemd.
- Exact assigned-head remote lookup: `gh api repos/Agent-StrongHold/Project-mAIstro/commits/ab1a30bf0ad545e12b0b53005383f68b37cbbb76/check-runs` returned HTTP 422, No commit found for SHA. Remote ref **not found; skipped** further remote investigation. No substitute refs or GitHub mutations. Hosted execution remains UNVERIFIED and cannot be resolved by this worker's authorized local commit.

## Fresh executed validation

Worker logs for the pytest runs are in the assigned job directory as
`check-worker-bootstrap.log`, `check-worker-rootful.log`, and
`check-worker-mode-floor.log`. These are newly executed checks, not inherited
verification claims.

- `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000 DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest packages/maistro-bootstrap/tests -x -q -rs`: **273 passed, 2 skipped** in 57.43s. All 18 qualifying-daemon conformance cases and the private-securityfs provisioning regression ran. Only Windows-specific behavior and the inverse rootful refusal case skipped.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon -x -q -rs`: **1 passed** in 5.26s.
- `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -x -q`: **15 passed** in 3.39s.
- `DOCKER_HOST=unix:///run/user/1000/docker.sock docker run --rm --network=none --memory=64m --memory-swap=64m maistro-builders:latest cat /sys/fs/cgroup/memory.max`: **67108864**, independently proving cgroup enforcement.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1403 reviewed / 1403 found; no unbanked identities. Ledger unchanged.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 2602 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests`: **passed**, 275 collected, matches inventory.
- `uv run python scripts/<gate>.py`: **passed** for `check-merge-markers`, `check-build-context`, `check-security-inventory`, `check-workflow-write-safety`, `check-required-checks`, and `check-doc-links`.

## Acceptance evidence

| Criterion | Current executed evidence |
|---|---|
| Filesystem, process, namespace/kernel, network, device, host socket, credential and privilege attacks | All 18 live qualifying-daemon cases passed against production `ContainerBuilderSandbox`. Kernel-surface assertions only; no hostile-kernel containment claim. |
| Network/credential default deny | Live public/private/metadata/DNS probes and populated host credentials plus Docker client proxy injection test passed. |
| Seed excludes `.env`, `.git`, unrelated host secrets | Live indexed-dotenv exclusion, untracked host secret/gitlink exclusion, and both replaced-index-path refusal cases passed. |
| Candidate is not container root | Live uid, capabilities, no-new-privileges and uid-map assertions passed; independent rootful refusal passed. Trusted empty-workspace ownership bootstrap is the sole root exec before seeding. |
| Read-only default / explicit workspace and scratch writes | Live read-only config and mount-by-mount write probes passed, including `/dev/shm` and `/dev/mqueue` refusal. |
| Timeout/kill/cleanup/resource exhaustion | Detached-descendant timeout, container removal and over-budget allocation cases passed; independent 64 MiB cgroup probe returned 67108864. |
| CI or designated hardware-capable lane runs suite | `.github/workflows/ci.yml:468-616` configures both daemon branches and executes the production suite. Private-namespace provisioning regression passed locally, but **hosted execution UNVERIFIED**: exact assigned candidate does not exist remotely. |
| SECURITY.md can cite real conformance evidence | Limitation 8 cites this real suite and prior live evidence, with explicit hosted-execution, AppArmor and Tier-3 limits. Fresh runs above independently reproduce local evidence. |
| Same backend as production | Tests directly instantiate `ContainerBuilderSandbox`; production `maistro_rsi.contained_validation:73-81` imports and instantiates that same class. No separately hardened fixture. |

## Handoff

Only this evidence note changes; test inventory delta is zero. No production,
workflow, security documentation or ledger edit is justified by these results.
The existing rootless daemon was used: this is not a fresh hosted-runner
provisioning claim. Tier-3 remains a shared-kernel guardrail, not Tier-1/2
containment; seed preparation assumes a stable trusted host worktree.

**BLOCKED** on hosted current-candidate execution. No push, dispatch, issue
mutation or integration approval was attempted. The previous block cannot be
resolved with an authorized local edit: an authorized owner must publish the
candidate and obtain actual hosted conformance results.

Progress: checked 1, done 0 (acceptance incomplete), skipped 0 issues, errors 1
(exact remote candidate lookup); next: authorized publication and hosted
validation. Commit this evidence checkpoint locally without speculative repairs.

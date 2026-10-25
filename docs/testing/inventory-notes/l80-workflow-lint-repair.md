---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 workflow-lint repair

## Frozen scope

- Issue #80 only; assigned `auto-80` worktree, starting HEAD `df00df2182339a6c71bf7405981f0cfee91d5c2e`, base `b43175c1d669826f9e413aaa83f7126149e5502c`.
- Repair targets: `.github/workflows/ci.yml`, `scripts/ci-rootless-mountns.sh`, and this evidence note. Review surrounding production sandbox, adjacent tests, SECURITY.md, support matrix, ADR-093/SPEC-190 and workflow lint configuration. Amend `quality/vulture-baseline.json` only if the required exact-debt gate identifies reviewed retained identities.
- Clean initial worktree; no incoming edits to salvage.
- Current job directory has no check logs. Prior result says live conformance passed but hosted CI was unverified; neither is accepted as current evidence.
- Assumption: this is the writer repair role; the verifier-only prohibition on edits does not apply.

## Progress

- Snapshot recorded before implementation. No GitHub mutations or remote operations planned.
- Read repository instructions, accepted ADR-093 and proposed SPEC-190. The supported container is only a supervised Tier-3 guardrail; no VM/hostile-kernel containment claim is justified. This repair does not change canonical execution authority.
- Exact CI actionlint 1.7.7 with ShellCheck 0.10.0 passed against the starting tree. The reported workflow-lint failure is not yet reproduced; run its remaining component gates before proposing edits.
- Required vulture exact-debt command passed: 1403 reviewed identities / 1403 findings, zero unclassified. No ledger amendment warranted.
- All remaining workflow-lint components passed (standalone ShellCheck, scope resolver fallback, required checks, uv setup, workflow write safety, branch protection). Log: current job `check-worker-workflow.log`. Merge-group event-specific scope is not reproduced without its event payload.
- Fresh rootless package run: **273 passed, 2 skipped** in 31.48s, including all 18 qualifying-daemon conformance cases and the private-securityfs provisioning regression. Only Windows-specific behavior and inverse rootful refusal skipped. Log: current job `check-worker-bootstrap.log`.
- Existing rootless daemon reports seccomp/rootless/cgroupns, cgroup v2/systemd; rootful daemon reports seccomp/cgroupns, cgroup v2/cgroupfs. This is not fresh hosted provisioning evidence.
- Because the reported lint failure does not reproduce, made one read-only exact-head check-run lookup to seek actual evidence. `gh api repos/Agent-StrongHold/Project-mAIstro/commits/df00df2182339a6c71bf7405981f0cfee91d5c2e/check-runs` returned **HTTP 422: No commit found for SHA**. Remote candidate **not found; skipped**. No alternate refs or repeated remote enumeration; hosted validation remains UNVERIFIED.

## Executed validation

All commands ran in the assigned worktree, with up to 1200-second validation timeouts.
Logs named below are in `/home/dev/maistro/jobs/42aba781a1d342629d3f7ab6e1817796`.

| Command | Outcome |
|---|---|
| `/tmp/actionlint -no-color -oneline -shellcheck /tmp/shellcheck-bin` | Passed using CI-pinned actionlint 1.7.7 and ShellCheck 0.10.0. |
| `/tmp/shellcheck-bin --severity=warning tools/*.sh` | Passed. |
| `uv run python scripts/ci_merge_group_scope.py --github-outputs` | Passed conservative all-enabled fallback; no GitHub event payload locally. |
| `uv run python scripts/<gate>.py` for `check-required-checks`, `check-uv-setup`, `check-workflow-write-safety`, `check-branch-protection` | All passed; `check-worker-workflow.log`. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed, 1403 reviewed / 1403 found. Ledger unchanged. |
| `MAISTRO_TEST_ROOTLESS_LANE=1 XDG_RUNTIME_DIR=/run/user/1000 DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest packages/maistro-bootstrap/tests -x -q -rs` | 273 passed, 2 posture/platform skips; `check-worker-bootstrap.log`. |
| `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon -x -q -rs` | 1 passed; `check-worker-rootful-floor.log`. |
| `DOCKER_HOST=unix:///run/user/1000/docker.sock docker run --rm --network=none --memory=64m --memory-swap=64m maistro-builders:latest cat /sys/fs/cgroup/memory.max` | `67108864`; actual memory limit enforced. |
| `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -x -q` | 15 passed; `check-worker-rootful-floor.log`. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed, 2602 files. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests` | Passed, 275 collected. |
| `uv run python scripts/<gate>.py` for `check-merge-markers`, `check-build-context`, `check-security-inventory`, `check-doc-links` | All passed; `check-worker-gates.log`. |

## Acceptance review

| Issue criterion | Fresh evidence |
|---|---|
| Filesystem, process, namespace/kernel, network, device, host socket, credential and privilege attacks | All 18 qualifying-daemon conformance cases ran and passed through production `ContainerBuilderSandbox`; namespace/mount probes establish Tier-3 surfaces, not hostile-kernel containment. |
| Network/credential default deny | Real public/private/metadata/DNS attempts denied; populated host credentials and Docker client proxy injection absent in candidate environment. |
| Seed excludes `.env`, `.git`, unrelated host secrets | Live indexed-dotenv, split-index, untracked-secret/gitlink exclusion and replaced-index-path refusal tests passed. |
| Untrusted work is non-root | Live uid/capability/no-new-privileges/uid-map probes passed. Independent rootful refusal passed. Only trusted empty-workspace ownership bootstrap uses container root, before seeding. |
| Read-only default and explicit scratch/workspace writes | Live rootfs configuration and mount-by-mount write probes passed, including read-only `/dev/shm` and `/dev/mqueue`. |
| Timeout/kill/cleanup/resource exhaustion | Detached-descendant timeout, force-removal and over-budget allocation tests passed; independent 64 MiB cgroup enforcement probe returned 67108864. |
| CI/designated capable lane runs suite | CI definition at `.github/workflows/ci.yml:468-616` configures both branches; local rootless execution and private-securityfs provisioning regression passed. **Hosted candidate execution UNVERIFIED**; exact head absent remotely. Existing daemon validation does not prove fresh hosted daemon provisioning/image load. |
| SECURITY.md can cite real backend evidence | `SECURITY.md:316-372` cites the real production suite with explicit Tier-3, AppArmor and hosted-execution limitations. Current local runs independently confirm the cited behavior. |
| Same backend as production, not a separate hardened fixture | Live tests directly instantiate `ContainerBuilderSandbox`; production `packages/maistro-rsi/src/maistro_rsi/contained_validation.py:73-81` imports/instantiates the same class. |

## Handoff

**BLOCKED**: no reported workflow-lint component failure reproduces, and no
current hosted candidate/check log is reachable. A speculative workflow or
ledger edit would not address actual evidence. Only this evidence note changes;
no tests, production code, workflow or ledger changed. Inventory delta is zero.

An authorized owner must supply the failed workflow-lint log/event payload or
publish the candidate and obtain hosted conformance results. This worker did
not push, dispatch, mutate GitHub or grant integration approval. The container
remains a shared-kernel supervised Tier-3 guardrail; seed preparation assumes a
stable trusted host worktree.

Progress: checked 1 issue, done 0 (acceptance incomplete), skipped 0 issues,
errors 1 (exact remote head lookup); next: hosted failure evidence and validation.
This note is committed locally as the preserved checkpoint.

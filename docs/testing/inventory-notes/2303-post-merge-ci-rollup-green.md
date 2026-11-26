# #2303 post-merge CI rollup green at dcfd061ebb (final verification round)

No suite-count delta: no test was added, removed, renamed or skipped by this
round. This is a verification-only round over the merge
`dcfd061ebb69fb94729ae47c36d9efe72ef2151a` (merge of `f927334a2e` — develop's
M2-B1 unattended-isolation backend — into the branch), which is the exact
dispatch head for the round.

## Why this round existed

The lane brief carried a stale gate-failure list ("Container scan + SBOM +
cosign, Coverage gate, Quality / Image pins, Quality gate (Pillars 1–4, 7, 8),
test" red) sourced from the older evaluation at `d754936fea`. Since then the
repair series (`58cc1eb`, `d754936`, `fb2872c`) landed, CI ran fully green on
`5b967946b1` (recorded in `2303-digest-pull-and-harness-build-verification.md`),
and the branch then absorbed develop's M2-B1 via `dcfd061ebb`. This round
re-proved every named gate against that new head instead of trusting either
the stale list or the pre-merge green run.

## Gate-relevant inputs are unchanged by the merge

`git diff 5b967946b1..dcfd061ebb` touches none of the issue's surfaces:
`quality/image-pins.json`, `packages/hive-conductor/tests/Dockerfile.playwright`,
`packages/hive-conductor/Dockerfile`, `tests/test_devskim_scan_scope.py`, and
`packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts` are
byte-identical to the head whose CI run was all-green. The merge's 79-file
delta is develop's own M2-B1 content (sandbox substrate, docs, inventory
notes), which develop's own merge-queue run already gated. `git merge-base
HEAD origin/develop` = `f927334a2e` = `origin/develop`, so the branch is a
clean superset of the current develop tip; GitHub reports the PR MERGEABLE.

## Live CI at dcfd061ebb (statusCheckRollup, queried 2026-11-17 ~05:45Z)

Every gate named by the lane brief concludes SUCCESS at this exact head:

| Gate | CI evidence |
| --- | --- |
| Container scan + SBOM + cosign | SUCCESS, run 44021242178, completed 05:22:12Z |
| Coverage gate (publish-set floor + diff coverage) | SUCCESS, run 44021242457 (its three producer shards — coverage (no services), (MinIO), (PostgreSQL) — all SUCCESS) |
| Quality / Image pins | SUCCESS, run 44021242457 |
| Quality gate (Pillars 1–4, 7, 8) | SUCCESS, run 44021242457 (all 36 needs green) |
| test | SUCCESS, run 44021242158 |
| exact-debt-ledger | SUCCESS, run 44021242457 |
| hive-conductor-e2e-ui (builds and drives the bumped playwright image) | SUCCESS, run 44021242158 |
| hive-conductor-e2e, docker-build, docker-rebuild-compare | SUCCESS |

75 of 75 concrete checks pass; the only non-passing entry is the `gates-ran`
aggregate status, still PENDING — GitHub-side rollup timing (its run URL
rotates as it re-polls), the same residual noted by the previous round, not a
gate this branch can fix.

## Local re-execution at dcfd061ebb (CI's exact arguments)

| Check | Command | Result |
| --- | --- | --- |
| Driver battery | `uv sync --locked --extra dev`, `uv run ruff check .`, `uv run ruff format --check .` | all exit 0 (this job's `check-0/1/2.log`) |
| Image pins gate | `RATCHET_BASE_REV=origin/develop uv run python scripts/check-image-pins.py` | 9 pins / 10 Dockerfiles, exit 0 |
| Vulture ledger (CI's exact scan args) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1236 reviewed identities → 1236 findings, exit 0; ratchet base `f927334a2e` → candidate `dcfd061ebb` (the merged develop, so the ledger rows develop's M2-B1 removed are consistent) |
| DevSkim scope guard (the branch's changed test) | `uv run pytest tests/test_devskim_scan_scope.py -q` | 21 passed in 1.57s (memoized helpers) |
| Suite inventory | `PATH=.venv/bin:$PATH python3 scripts/check-suite-inventory.py` | 21 suites match, 35459 unique identities, 0 duplicates, exit 0 |
| Pinned digest resolves | `docker manifest inspect mcr.microsoft.com/playwright@sha256:47b510d…` | OCI index with linux/amd64 → `d65108d1…`, linux/arm64 → `969a9e36…` — byte-for-byte the per-arch move recorded in `quality/image-pins.json` |

Digest pull, harness build (`Version 1.64.1`), and spec collection (246 tests /
47 files) were proven at `5b967946b1` and the harness Dockerfile is unchanged;
this head's green `hive-conductor-e2e-ui` run additionally builds and drives
the bumped image end-to-end in CI.

## Residual risks

- `gates-ran` aggregate PENDING at write time: rollup timing only; every
  concrete check it aggregates is SUCCESS.
- The container gate's five-image buildx + Trivy/Grype/cosign execution is
  proven by CI's green run at this head, not locally re-executed (45-minute
  cold-cache job); local evidence covers the digest chain, pins ledger, and
  harness function.

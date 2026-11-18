# CR-1640: container-gate verification (round 4, exact merge head `5062a0c904`)

Evidence-only round (no suite delta): no tests, workflows, dependencies,
grants, ledgers or gate rules are changed. Head `5062a0c904` (branch
`chatgpt/1629-acceptance-delivery-planner` after merging origin/develop
`d0e8e235a8`: the #2120 node 22-alpine -> 26-alpine bump with its frontend
lockfile regeneration, the #2387 lizard bump, and the merge resolutions
recorded in that commit message). Develop base `d0e8e235a896`.

Why a fourth round: the merge-queue evaluation that reported
"Container scan + SBOM + cosign: failure" ran against the merge-group tree of
PR head `1cbb30b829` with develop `d0e8e235a8`. The conflict was resolved in
place by merge commit `5062a0c904` (mutation.yml keeps the branch's
no-paths-filter pull_request trigger and folds develop's image-pins rationale;
security-scan SKILL.md takes both sides), but every prior container/SBOM
evidence note predated that merge, so the named failing gate had no evidence at
the tree the merge queue actually saw. This note supplies it.

## The develop sync diagnosis, in one paragraph

GitHub reported PR #1640 `mergeable: CONFLICTING` against `d0e8e235a8`
(`git merge-tree origin/develop 1cbb30b829` exits 1 with content conflicts in
`.github/workflows/mutation.yml` and `.claude/skills/security-scan/SKILL.md`).
GitHub's merge-queue machinery therefore could not produce a mergeable commit;
the visible container-gate failure label belongs to that stuck evaluation, not
to a scanner regression. The branch's own diff vs `d0e8e235a8` (verified with
`git diff --name-only origin/develop...HEAD`) touches 25 files: `.claude/skills`,
`.github`, `CHANGELOG.md`, `docs/`, `quality/`, `tests/`, `tools/` — none of
which any Dockerfile COPYs into an image, so the five images built at this head
have content-identical inputs to the images CI already scanned green at
`d0e8e235a8` (merge-group run 44056318160, `security` SUCCESS). The develop
merge DID change image inputs relative to `1cbb30b829` (node 26-alpine stage,
both frontend lockfiles), which is why fresh evidence at this tree, rather than
the round-3 note, is the honest requirement.

## Local reproduction at the exact head (this round, all executed)

All five images rebuilt from `5062a0c904` with `scripts/buildx-build-retry.sh`,
CI's build arguments and the exact `--no-cache-filter` stages (the local Docker
cache substitutes for CI's unavailable `type=gha` backend; the apt patch stages
re-executed rather than replayed). Logs: job dir `r4-logs/build-*.log`.

- Builds: `hive-conductor:pr-cr1640-5062a0c`,
  `hive-conductor-observability:pr-cr1640-5062a0c`,
  `maistro-engine:pr-cr1640-5062a0c`,
  `maistro-engine-research:pr-cr1640-5062a0c`,
  `maistro-rsi-runner:pr-cr1640-5062a0c` — rc=0 x5.
- CI's live identity/version one-liners on both Conductor images: rc=0 x2
  (python 3.13.18, bip-utils 2.12.2, coincurve 21.0.0, pynacl 1.6.2,
  `ConductorSeed.generate()`; observability additionally imports
  opentelemetry + OTLP exporter).
- **Trivy 0.73.0** (CI-pinned action version), `--severity HIGH,CRITICAL
  --ignore-unfixed --exit-code 1 --ignorefile .trivyignore.yaml`: **rc=0 on all
  four scanned images** (`r4-logs/trivy-*.log`). This is the named failing
  check, now proven green at the exact head.
- **Grype 0.116.0** (CI-pinned), `--fail-on high --only-fixed`: rc=0 on all
  four (`r4-logs/grype-*.log`). The residual finding set is unchanged from
  round 3 (python 3.13.18 Medium/Low binary advisories; RSI runner's
  python 3.12.16 / pip 25.0.1 Medium set) — no new findings from the develop
  merge. Disk-backed `TMPDIR` avoided the stereoscope `/tmp` tmpfs exhaustion
  seen in earlier rounds.
- **Lock reconciliation** (CI's exact four `uv export --locked` exports +
  `scripts/check-image-lock-reconciliation.py` member assertions): rc=0 x4 —
  maistro-engine 126 distributions, hive-conductor 74, research 147, RSI runner
  220, matching the round-3 measurements exactly.
- **Frontend license surfaces**: `npm ci` + `npm run build` rc=0 in both
  frontends under host node v22.22.1 (same major as CI's setup-node), proving
  the post-merge lockfiles build. Syft 1.49.0 produced all eight workflow SBOM
  surfaces including the Conductor bundle extracted from the final image;
  `scripts/check-license-inventory.py` rc=0: **8 surfaces, 25,296 components,
  copyleft=419 (policy=review)** — identical to round 3.
- **Cosign**: no signing step exists in the current workflow (removed by
  design, documented in `security.yml` itself: local-only tags are not
  verifiable release digests). Nothing to run; no signing success is claimed.

## Acceptance-state ratchet + mandate at the exact head and assigned base

Executed CI's exact command
`uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate d0e8e235a896…`
(`r4-logs/ac-state-mandate-pg.log`), after starting the CI-equivalent service
(`pgvector/pgvector:pg18`, user/db `maistro`/`maistro_test` on 127.0.0.1:55499,
`MAISTRO_TEST_PG_DSN`/`DATABASE_URL` exported, `uv run alembic upgrade head`
rc=0). Result **rc=0**: design coverage **44.4608% over 166 taken decisions
(87 at zero)** — digit-identical to CI's run at `1cbb30b829` (job 133896875608,
run 44041487290) — all 10 debt counters exactly on their ceilings, the progress
counter exactly on its floor, every declared criterion proven, and the chain
mandate clean. The authorized floor (39.641, grant #166 from the base's notes)
is nowhere approached.

First attempt without the postgres service failed honestly at
`design_coverage 39.8641 ... (88 at zero)` — one service-backed decision's
`@pytest.mark.ac` evidence does not reach the passing rung without a database.
That failure is the documented environment gap, not a tree regression: the
preserved generated `quality/ac-state.json` from the pre-merge head measures
the identical 39.8641 with identical per-decision rows, proving the develop
merge changed nothing in the measured tree. CI's acceptance-state job declares
its postgres service in `quality.yml`; the local reproduction now matches it.

## Supporting gates re-run at this exact head

`uv run ruff check .` and `uv run ruff format --check .` rc=0; focused
`uv run pytest tests/test_plan_delivery.py tests/test_check_required_checks.py
tests/test_distribution_contract.py tests/test_mutation_targets.py -x -q`:
**161 passed**; planner-only coverage re-measured: **56 passed,
tools/plan_delivery.py 236 stmts / 1 miss = 99%**. CI-exact gate scripts, all
rc=0: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (1236 == 1236 identities), `check-suite-inventory.py` (21
suites), `check-workflow-inventory.py`, `check-image-pins.py`,
`check-image-inventory.py`, `check-required-checks.py`,
`check-branch-protection.py`, `check-ratchet-provenance.py`,
`check-shipped-surface-truth.py`, `check-test-duplicates.py`.

## Coverage gate at the exact head — structural proof + CI citation

Not re-run end-to-end locally this round (the producer is ~13 sequential
coverage runs); the outcome is pinned instead:

- The publish-set floor is computed over `packages/*` sources, `scripts/`,
  `packages/hive-conductor/backend`, `alembic/`, `config/` — all byte-identical
  between this head and `d0e8e235a8` (the branch diff touches none of them,
  verified above). CI's coverage battery at exactly `d0e8e235a8` (quality run
  44062413306, push develop) reports **"Coverage gate (publish-set floor +
  diff coverage)" success**, as do coverage (no services), (PostgreSQL) and
  (MinIO).
- The diff-coverage half is scoped to files this candidate changed vs the base:
  four `tests/` files (exempt by `EXEMPT`'s `/tests/` entry in
  `scripts/check-diff-coverage.py`) and `tools/plan_delivery.py`, which lies in
  no `MEASURED_ROOTS` — the gate names it "unmeasured" in the log without
  failing, exactly as CI's own raw log shows at `1cbb30b829` (round-3 citation,
  job 133904005971). The changed-file set at this head is identical to that
  green evaluation.

## Remaining handoff, not integration approval

The remote PR head is still `1cbb30b829`; this worktree's merge resolution and
this evidence commit have not run remote CI and have not received independent
final review. The PR body remains stale (obsolete head/path/test count and the
obsolete "no workflow or ratchet changes" claim); remote edits are prohibited
in this lane and must be reconciled by an authorized owner. No merge approval,
push, comment, issue closure or gate waiver is implied.

Raw logs: `/home/dev/maistro/jobs/2cdc9611afce4f2a9ad4b94d25752bc1/r4-logs/`.

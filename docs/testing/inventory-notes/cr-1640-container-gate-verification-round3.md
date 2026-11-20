# CR-1640: container-gate verification (round 3 and exact-head supplement)

Historical round-3 record, no suite delta. Head `c6261a9b96` (branch
`chatgpt/1629-acceptance-delivery-planner` after merging develop's
M2-B1 `f927334a2e`, which moved `uv.lock`, `quality/image-pins.json`
and the sandbox packages); develop base `a660bc2a9d0`.

Why a third round: the merge-queue evaluation that reported
"Container scan + SBOM + cosign: failure" predated this head. Round 2
(`cr-1640-container-gate-reverification.md`) proved the gate at
`b4f644367d`, i.e. before the M2-B1 merge changed image inputs again,
and left grype-on-research/rsi-runner, the lock reconciliations, the
live version asserts and the SBOM/license inventory unproven locally.

CI evidence at this exact head (verified via
`gh api .../actions/runs/44022092973`: `head_sha == c6261a9b96`):
the `security` workflow's "Container scan + SBOM + cosign" job
completed SUCCESS at 2026-11-17T05:32:47Z, and the PR rollup at this
head is green for every named gate (test, Quality, coverage,
exact-debt-ledger, devskim, mutation, lint-and-type-check).

Local reproduction at this head (WSL docker daemon healthy; all five
images rebuilt from `c6261a9b96` with CI's `--no-cache-filter` args):

- Builds: `hive-conductor:pr-cr1640-verify`,
  `hive-conductor-observability:pr-cr1640-verify`,
  `maistro-engine:pr-cr1640-verify`,
  `maistro-engine-research:pr-cr1640-verify`,
  `maistro-rsi-runner:pr-cr1640-verify` — all OK.
- Version/identity asserts (CI's exact one-liners): both Conductor
  images report python 3.13.18, bip-utils 2.12.2, coincurve 21.0.0,
  pynacl 1.6.2; observability additionally imports opentelemetry +
  OTLP exporter. RC=0 both.
- Trivy `--severity HIGH,CRITICAL --ignore-unfixed --ignorefile
  .trivyignore.yaml --exit-code 1`: RC=0 on all four scanned images.
- Grype `--fail-on high --only-fixed`: RC=0 on all four. The research
  image initially failed with `no space left on device` in
  stereoscope's `/tmp` cache (tmpfs at 93%); rerun with `TMPDIR` on a
  roomier filesystem passed with zero matched findings —
  infrastructure, not the gate.
- Reconcile installed packages to uv.lock (CI's exact four
  invocations incl. `--member` asserts): "ships exactly the locked
  set" for maistro-engine (126 dists), hive-conductor (73),
  maistro-engine-research (147), maistro-rsi-runner (220). RC=0 x4.
- Frontend license surfaces rebuilt from scratch (`npm ci` + `npm run
  build` in both frontends), then syft SBOMs for the four images plus
  the four directory surfaces and
  `scripts/check-license-inventory.py`: "OK: inventoried 8
  surface(s), 25292 component(s); copyleft=419 (policy=review)". RC=0.
- Cosign: signing is removed by design (`.github/workflows/security.yml`
  documents the removal; no signing step to verify).

Supporting gates re-run at this head:
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` RC=0 (1236 == 1236 identities);
`scripts/check-suite-inventory.py` RC=0 (21 suites match);
`uv run pytest tests/test_plan_delivery.py -q` 56 passed — matching
the reconciled +54/+2 split between the delivery-planner and
reservation-scope notes.

## Exact-head repair-lane supplement: `1cbb30b829`

This supplement validates the assigned starting head
`1cbb30b8290b64fc07deccc4f72505eac804d58d`, against assigned develop base
`a660bc2a9d0b1637256ce7eab13a7997fafc0575`. It does not retroactively
attribute the historical results above to that head. This round changes only
this evidence note; no tests, workflow rules, dependencies, grants or ledgers
are changed. No suite-inventory delta.

### Diagnosis, rather than speculative repairs

The supplied dispatch snapshot already records **SUCCESS** for the named
"Container scan + SBOM + cosign" check at the assigned head: security run
`44041486931`, job `133896873948`. Its stale failure label is not evidence of
an outstanding source defect. Earlier attempts were interrupted by provider
retirement/authentication and local disk exhaustion, not demonstrated new
scanner findings. The existing fixes were preserved, not restarted.

Local reproduction independently passed the full container contract:

- Rebuilt all five images with `scripts/buildx-build-retry.sh`, explicit
  `--builder default`, `--load`, CI's build arguments and the exact
  `--no-cache-filter runtime-apt` / `production-apt` stages. Tags:
  `{hive-conductor,hive-conductor-observability,maistro-engine,maistro-engine-research,maistro-rsi-runner}:pr-cr1640-1cbb30b829`.
  Local Docker cache replaces the unavailable GitHub cache backend; the apt
  patch stages were re-executed, not accepted from cache.
- CI-pinned Trivy 0.73.0, `--severity HIGH,CRITICAL --ignore-unfixed
  --ignorefile .trivyignore.yaml --exit-code 1`: RC=0 on all four scanned
  images. Grype 0.116.0, `--fail-on high --only-fixed`: RC=0 on all four.
  Disk-backed `TMPDIR` avoided the previously exhausted `/tmp` tmpfs.
  Lower-severity findings remain; this is not a claim of zero vulnerabilities.
- Both workflow live identity/version one-liners passed, including
  `ConductorSeed.generate()` and the observability imports.
- Both frontends: `npm ci` and `npm run build` passed. Syft 1.49.0 generated
  all eight workflow SBOM surfaces, including the Conductor bundle extracted
  from the final image. `check-license-inventory.py` with CI's policy and
  surface/artifact arguments passed: **8 surfaces, 25,296 components,
  copyleft=419 (policy=review)**.
- All four workflow lock exports and
  `check-image-lock-reconciliation.py` member assertions passed: engine 126,
  Conductor **74**, research 147, RSI runner 220 distributions. Unlike the
  historical build above, this head includes Conductor's merged `tzdata`
  member assertion. The difference was actually measured, not inferred.
- There is no cosign signing step in the current workflow. Signing was
  explicitly removed upstream because local-only tags are not verifiable
  release digests; no signing success is claimed here.

No Vulture amendment was justified: the required exact command
`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` passed, **1,236 reviewed
identities == 1,236 findings**, zero unclassified.

### Acceptance and repository validation

- `uv run pytest tests/test_plan_delivery.py tests/test_check_required_checks.py
  tests/test_distribution_contract.py tests/test_mutation_targets.py -x -q`:
  **161 passed**. Planner-only branch coverage: **56 passed, 99%**, 236
  statements / 62 branches; only the `__main__` exit is missed. Independent
  executable probes also exercised all four slice kinds and milestone-first
  ordering. Both reservation regression tests passed with production code and
  failed when the task-scope union was removed **in memory**, without editing
  the worktree. The first probe harness expected only `AssertionError`; the
  corrected replay also recognizes the second test's missing-blocked-row
  `KeyError` as a rejected regression.
- These tests exercise complete reviewed exact-base evidence, dependency
  closure, cycle/missing-dependency refusal, invalid scopes/duplicate evidence,
  parked and active ownership, shared resources, bounded WIP, deterministic
  ranking, and stale/moved-base/incomplete-census suppression. The actual seed
  CLI returned **2**, advisory-only, with refresh reasons and **no selection**.
- Inspected the dated closeout/M1/M2/M3/release plan and operator skill. The
  planner remains read-only repository tooling, not a second scheduler or
  Goal/Graph/Run authority (ADR-081226-a66b). No external cadence integration
  or issue closure is claimed. Existing workflow-reporting repairs and the
  AC-state improvement note are validation changes, not new planner authority;
  the original issue/PR's blanket claim of no workflow/ratchet changes is now
  obsolete and must not be repeated.
- `uv run ruff check .` and `uv run ruff format --check .`: RC=0.
  Suite inventory (21 suites), workflow inventory, required checks, branch
  protection, canonical execution lifecycles, documentation links, image pins
  and image inventory gates all passed.
- Reproduced the earlier environmental root-suite obstruction directly:
  `tests/test_branch_independence_repository.py:18` rejects the pre-existing,
  ignored generated `quality/ac-state.json` as unclassified. Preserved that
  file in the job directory, temporarily isolated it from the source-only
  scan, and reran **all root tests with no deselections**, using disk-backed
  `TMPDIR`: **5,971 passed, 139 skipped**, RC=0 (428.23s). Restored the original
  generated file unchanged afterward. This is an environment-qualified result,
  not a claim that the unqualified dirty-environment command passes or that
  skipped service-dependent acceptance ran.

Read-only downloads of the **individual supplied job IDs**, not a refreshed
PR/check census, resolved the prior pending CI evidence:

- Coverage job `133904005971`, run `44041487290`: completed **SUCCESS**;
  metadata confirms `head_sha == 1cbb30b829...`. Raw log reports publish-set
  coverage **95%**, above the 87% floor. Diff gate passes but explicitly marks
  `tools/plan_delivery.py` **unmeasured** (no CI producer for `tools/`); four
  changed test files are exempt. Direct local planner coverage above supplies
  additional evidence, not an assertion that CI measured it
  (ADR-082526-cb51).
- Test job `133896874574`, run `44041487086`: completed **SUCCESS**, same
  confirmed head. Raw log includes the root suite's **5,878 passed / 139
  skipped**, plus its separate package/frontend validation steps.
- Acceptance-state job `133896875608`, run `44041487290`: the raw log executes
  `--run-tests --ratchet --mandate` against assigned base `a660bc2a9d0b...` and
  reports all debt/progress bounds satisfied and every newly declared criterion
  proven. No candidate grant or ledger change was made in this round.

Raw logs, scripts, SBOMs, job metadata and preserved generated evidence are in
`/home/dev/maistro/jobs/9b93f7b99b114ecf9a2a871ef6b9f7bc/`. In particular:
`build-*.log`, `trivy-*.log`, `grype-*.log`, `container-contracts.sh`,
`container-contracts.log`, `vulture.log`, `focused-tests.log`,
`planner-coverage.log`, `reservation-regression-probes.log`, `root-tests.log`,
`exact-head-{coverage,test,acceptance-state}.log` and `repair-progress.md`.

### Remaining handoff, not integration approval

The supplied PR body still names obsolete head `1c48ec7923`, path
`scripts/plan_delivery.py`, 54 tests and no workflow/ratchet changes. Actual
source is `tools/plan_delivery.py`, with 56 planner cases, the mutation-trigger
repair and the AC-state note. Updating remote metadata is prohibited in this
lane; an authorized owner must reconcile it. The evidence-only commit from
this round has not itself run remote CI or received independent final review.
No merge approval, push, comment, issue closure or gate waiver is implied.

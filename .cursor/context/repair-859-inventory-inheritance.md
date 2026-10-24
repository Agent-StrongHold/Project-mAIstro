# #859 / PR #2209 — inherited inventory delta repair

## Frozen scope and starting state

Writer lane in `/home/dev/Git/wt/auto-859`, branch `auto-859`, starting HEAD
`048727437d2855fd58a422c81c437af5253c11ca`; supplied develop base
`b9cd15c608b5cc23ce785b3c80813d7e4d8f678b`. Only #859 processed.
The worktree arrived clean, with no merge in progress or unmerged paths.
`origin/develop` resolves to the supplied base, already merged by starting HEAD;
the supplied conflict warning is stale. No fetch, merge, GitHub mutation, quality
ledger/grant edit, test removal, or production change was needed this round.

Read repository instructions, the supplied dispatch/check logs and prior result,
and ADR-092326-7ed7, ADR-092326-97c4 and proposed ADR-081426-fb9f. Accepted
ADR-092326-97c4 explicitly leaves the standalone Turing in-memory Workspace
composition unresolved. This repair does not claim shipped durable Workspace
convergence, activate Turing, or add an execution/identity authority.

## Reproduced defect and repair

Before editing, `uv run python scripts/check-suite-inventory.py --suite tests/`
failed: expected **5819**, collected **5811**, net **-8**.
`859-container-gate-base-pin-refresh.md` and the develop-inherited
`1152-container-gate-base-pin-refresh.md` both counted the same eight nodes in
`tests/test_pinned_digest_references.py`. The test and the associated Dockerfile,
Hive Dockerfile, smoke script and image-pin content have no diff against the
supplied develop base. This is duplicate accounting, not missing collection.

Withdraw only #859's duplicate delta; retain its historical explanation and
explain the inheritance. Preserve the genuine restore-readiness `tests/: +1`.
No tests added or changed; the existing inventory gate is the regression check.
The same command that failed now passes with 5811 nodes.

## Executed validation

Full logs: `/home/dev/maistro/jobs/3800f6e653fc4ed8b85cb6c056acbbfd/`.

- `uv run python scripts/check-suite-inventory.py`: **21 suites match**, 33739
  unique nodes; zero copied-test evidence. `writer-inventory-full.log`.
- Scoped inventory: root 5811, Turing backend 125, Turing package 225, all match.
  `writer-inventory-before.log` records the failing control;
  `writer-inventory-after.log` records the repaired result.
- `uv run pytest packages/maistro-turing/backend/tests packages/maistro-turing/tests -x -q`:
  **350 passed**, one existing `runpy` warning in provision CLI test.
  `writer-turing-tests.log`.
- `uv run pytest tests/test_pinned_digest_references.py tests/test_backup_restore_oracle.py tests/test_check_image_pins.py -x -q`:
  **67 passed** (terminal output).
- `uv run ruff check .`: passed; `uv run ruff format --check .`: 3466 formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, **1314 reviewed identities / 1314 findings**; no ledger amendment
  warranted. `writer-vulture.log`.
- `uv run python scripts/check-image-pins.py`: 8 pins / 10 Dockerfiles, passed.
  `check-image-inventory.py`: 9 Dockerfiles, passed. `check-build-context.py`:
  passed (all via `uv run python`).
- `git diff --check`: passed.

## Acceptance rechecked against reachable code and executed tests

All tests below ran in the 350-test command, not merely in earlier job logs.

1. Canonical principal scoping: real HTTP admin mood/facet changes resolve
   `scope_for(authenticated.user_id)`; two-user snapshot/facet tests prove
   different Workspace ids and unchanged foreign defaults.
2. Session ownership/bounds: `ChatSessionRegistry.resolve` keys by Workspace
   and session, with per-Workspace LRU and TTL; guessing, TTL, capacity,
   cross-Workspace eviction and timestamp-tie tests pass. Runtime history and
   failed-turn rollback bounds also pass.
3. Validated mutations: backend `set_mood`/`set_facet` validate before saving;
   rejected-new-scope tests prove nothing persisted. `store_episode` calls the
   tier clamp before persistence; clamping/malformed-weight tests pass.
4. Provenance/no global fallback: scope-less accessor tests pass; HTTP scope
   comes from auth, responses name the Workspace; chat session capture carries
   user/project identity into the memory bridge. Bridge provenance tests pass.
5. Restart: fresh-composition test proves documented ephemeral defaults and
   empty sessions. Shared-store facade tests exercise the optional shared seam,
   not a real durable adapter; no durable adapter is shipped by this slice.
6. Two-user/two-Workspace isolation: HTTP snapshots/facets and prompt-capturing
   guessed-session tests pass; guessed ids cannot acquire another user's history.
7. Boundaries: mood/facet invalid ranges, nonfinite/wrong-type mood/weights,
   tier clamps and rejected writes pass at the authoritative seams.
8. Replicas: composition rejects declared replicas with absent/local/unclassified
   state stores; shared-facade and deterministic-principal-scope tests pass.
   This is a fail-closed declaration contract, not evidence of a deployed
   multiworker durable Turing service.

## Container evidence and remaining uncertainty

The frozen dispatch's current-head container check has `conclusion: null`.
Reading that exact supplied job with
`gh run view 39897051712 --job 120229806239 --log` failed because the job is
**still in progress**, with logs unavailable (`writer-container-ci.log`). No
new failure diagnostics are available; do not invent a dependency/pin repair.

Locally rebuilt the actual engine from this worktree with the CI patch-stage
flag (Docker host `unix:///var/run/docker.sock`):

```
scripts/buildx-build-retry.sh -- -f Dockerfile -t maistro-engine:859-inventory-repair --no-cache-filter runtime-apt --load .
trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml maistro-engine:859-inventory-repair
grype maistro-engine:859-inventory-repair --fail-on high --only-fixed --output table
```

Build passed; Trivy **0 HIGH/CRITICAL** (0.73.0, DB updated 2026-10-23);
Grype **no HIGH/CRITICAL**, two Medium Python findings, exit 0 (0.116.0).
`writer-engine-{build,trivy,grype}.log` record the results. Engine image manifest
list: `sha256:cf3b329c93024685b398db6d9bd6bd89326f0f8797b1d39a51b6998e2c875021`.

**UNVERIFIED:** full container workflow's other image builds/scans and combined
SBOM/license gate. The supplied container-failure warning cannot be closed from
an in-progress job log or an engine-only local scan. Leave that evaluation to
the driver; this commit repairs the demonstrated inventory defect only.

Progress: checked 1 assigned issue, repaired 1 demonstrated defect, no skipped
issues. Handoff needs container-gate evidence before integration approval.

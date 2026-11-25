# Persistent Pi foremen and recovery

Optional operator tooling, not a product daemon or a second autonomous fleet.
Read [the runbook](../../docs/operations/pi-foremen.md) before operating it.

- `pi`: human control/recovery front door; recover the exact registered journal.
- `maistro`: operations, ownership and bounded stall diagnosis.
- `homie1`: one admitted repair with reproducible verification; idle if unassigned.
- Source: `scripts/pi_recovery/`; tests: `tests/pi_recovery/`.
- Native intercom messages, never terminal keystroke injection or destructive
  pane replacement. Liveness, delivery, progress and remote completion differ.
- Startup/pokes grant no implementation, publication, merge or service authority.
  Reconcile existing work/owners and full remote SHAs before effects; no replay.
- Repo-owned memory is this portable contract/runbook, not private conversations.
  Live IDs, assignments, journals, credentials and host evidence remain outside Git.

A clone provides code and instructions, not a running installation or restored
private memories. Nothing is armed by checkout, import, or test collection.

## CI status diagnosis (2026-10-25, verified round)

Every check run on head `c899163de` is success or legitimately skipped
(74 captured), and the Coverage gate (publish-set floor + diff coverage) was
reproduced locally: root suite 6092 passed / 139 skipped / 0 failed under
`coverage run --branch --source=scripts`, then
`scripts/check-diff-coverage.py coverage.xml --base origin/develop` exit 0
(all 9 changed `scripts/pi_recovery` modules ≥90% lines / ≥80% branch arcs).
The branch touches 0 files under `packages/`, so the publish-set floor is
structurally unaffected.

The only red surface is the required `gates-ran` commit status, stuck
`pending` ("Required execution evidence is still arriving"). Local simulation
of `scripts/check-gates-ran.py` over the captured head evidence returns exit 2
with exactly one absent check: **Mutation gate (changed critical lines)**.
Root cause, on the default branch, not this one:

- `.github/workflows/mutation.yml` triggers on `pull_request` with a
  `paths:` filter (`packages/**/*.py` + mutation governance artifacts) and has
  no `merge_group` trigger, so it can never produce a check run for a
  candidate whose diff matches no path — and never on a queue SHA at all.
- `scripts/check-gates-ran.py` `required_check_names()` keeps every
  PR-reachable job from `scripts/check-required-checks.py` `collect()` and
discards the row's recorded `paths` scope, so the mutation gate is demanded as
  execution evidence on every candidate. Absence is classified pending, never
  excused (it is not in `PATH_SCOPED_CHECKS`).
- `.github/branch-protection.json` documents the same trap for branch
  protection: a paths-filtered job cannot be required "without waiting on
  `Expected` forever".

By design the publisher evaluates with default-branch code, so no candidate
branch can repair its own `gates-ran` verdict. Operator repair options:
(a) teach the evaluator/measured-envelope to excuse the mutation gate when no
mutation-critical file changed (mirror `PATH_SCOPED_CHECKS` with a `mutation`
leg in `scripts/ci_merge_group_scope.py`), or (b) give mutation.yml a
`merge_group` trigger and drop the `paths:` filter, exactly as its own
branch-protection note prescribes before requiring it.

## Coverage gate re-proven at head 99eda89ee (2026-10-26, verified round)

The cancelled CI run (job 121397566077, run 40240833368) never reported a gate
failure — it died to runner/agent budget exhaustion. The gate was re-proven
locally at the current head, after the two develop syncs (cbfa25c94, 99eda89ee
bringing develop to 78133c093), with CI's exact commands and base:

- Root producer, exact `quality.yml` argv: `coverage run --append --branch
  --source=scripts -m pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30
  -q` → 6098 passed / 139 skipped / 0 failed in 11m10s (RATCHET_BASE_REV set,
  as a PR run would).
- `coverage xml` then `scripts/check-diff-coverage.py coverage.xml --base
  78133c093e0a5cd0d2a7e8538afa703521c70d07` → exit 0: 9 changed
  `scripts/pi_recovery` modules measured, all ≥90% lines / ≥80% branch arcs;
  the 6 `tests/pi_recovery` files are exempt as evidence, by declaration.
- Publish-set floor (87%): structurally unaffected — `git diff --stat
  78133c093..HEAD -- packages/` is empty, and the floor is evaluated in the
  combine step before any scripts-producer data joins, from the three upstream
  producers whose measured trees are byte-identical to the base.
- `scripts/check-suite-inventory.py` → ok, 21 suites, `tests/: 6215` and root
  collection reproduces exactly 6215 (+177 = +85 `pi-foremen-recovery` + +92
  `pi-foremen-recovery-coverage`).
- Vulture ledger with CI's exact argv → 1253 reviewed identities = 1253
  findings, base resolved to 78133c093. Ruff check/format, check-test-duplicates
  and `tests/test_check_diff_coverage.py` (18) all green; `systemd-analyze
  --user verify` clean on all four shipped unit templates; `pytest
  tests/pi_recovery` 177 passed + 32 subtests in 2.1s.

No tree change was required this round: the repair of record remains 40ada5e6e
(92 offline cases), which survives both develop syncs. The only red surface is
still the default-branch `gates-ran` evaluator trap documented above.

## Coverage gate re-proven at head d08ea3747 (2026-10-26, verified round)

Re-proven after two further develop syncs (5c7c6b16f bringing develop to
05070ff07, d08ea3747 bringing develop to 10f872fa7), with CI's exact commands
and base. The cancellation at 789aa94e7 was never a gate failure; the last
merge-queue evaluation simply predated this head.

- Root producer, exact `quality.yml` argv with RATCHET_BASE_REV=origin/develop:
  6100 passed / 139 skipped / 0 failed in 12m50s (+2 over the 99eda89ee round
  from the develop syncs).
- `coverage xml` then `scripts/check-diff-coverage.py coverage.xml --base
  407b181c46b4f532dbad4b64d0c2195e7a814f75` (develop's tip, the PR base) →
  exit 0: the same 9 measured `scripts/pi_recovery` modules, 6 exempt test
  files. The three-dot diff resolves to merge-base 10f872fa7.
- Publish-set floor (87%): `git diff HEAD 10f872fa7 -- packages/maistro-{core,
  canvas,evolve,rsi,bootstrap}` is empty — the floor's measured trees are
  byte-identical to the merge base, and the floor is evaluated before any
  scripts-producer data joins.
- Develop's tip 407b181c (#2333, ADR-044 AssetInstance connect) is one commit
  ahead of the branch's merge base. A naive two-dot diff vs develop tip shows
  -82/-37/-6/-215 lines in canvas/server files: those are develop's OWN new
  lines absent from the branch, not branch deletions. The branch's diff vs the
  merge base is pure addition (27 files: pi_recovery + docs). The next develop
  sync should take #2333's content wholesale.
- Suite inventory via `uv run python scripts/check-suite-inventory.py` → ok,
  21 suites, `tests/: 6217`; vulture with CI's exact argv → 1248 reviewed =
  1248 findings, base resolved to 10f872fa7; ruff check/format,
  check-test-duplicates, `tests/test_check_diff_coverage.py` (18) and
  `systemd-analyze --user verify` on the four unit templates all green;
  `pytest tests/pi_recovery` 177 passed + 32 subtests.

No tree change was required this round either; the branch at d08ea3747 is
proven against every gate the cancelled run would have evaluated.

## Container scan + SBOM + cosign re-proven at head a79a689ae3 (2026-11-16, verified round)

The named red gate for the a11908f33 merge-queue evaluation. Two commits are
the repair of record: a11908f338 (npm audit-level=high in ci.yml/security.yml,
the conductor Dockerfile frontend stage, and refreshed lockfiles) and
a79a689ae3 (python 3.13.18-slim / refreshed 3.12-slim base-digest bumps with
quality/image-pins.json rows, docker/cli v29.9.1 dockerclibuild stages
upgrading go-jose/v4 v4.1.6 + klauspost/compress v1.20.2 + golang.org/x/net
v0.62.0 and re-vendoring, pyproject floors oauthlib>=4.0.1 pyasn1>=0.6.5
pypdf>=6.21.4 soupsieve>=4.0.0 temporalio>=1.36.1 playwright>=1.65.2
patchright>=1.64.4 with uv.lock, project-level .npmrc audit pins, security.yml
identity asserts moved to 3.13.18). Nothing weakens a gate: every fix upgrades
a real shipped artifact; the scanners and their flags are unchanged.

Re-proven locally against the shared daemon image set tagged `pr-local`, whose
content was verified to match THIS tree before use as evidence (the stale
`pr-verify2304`/`pr-repair` sets carry intermediate states — e.g. temporalio
1.34.0, playwright 1.64.0 — and were discarded as evidence):

- Image content == tree: engine python 3.13.18 and its /usr/local/bin/docker
  embeds go-jose v4.1.6 / compress v1.20.2 / x/net v0.62.0 (`go version -m`);
  research = oauthlib 4.0.1, pyasn1 0.6.5, pypdf 7.1.0, soupsieve 4.1.1,
  playwright 1.65.2, patchright 1.64.4, python 3.12.16; rsi = temporalio
  1.36.1 — all equal to uv.lock.
- Trivy v0.73.0, CI parameters (HIGH,CRITICAL, exit-code 1, ignore-unfixed,
  .trivyignore.yaml): all four images exit 0, zero findings.
- Grype v0.116.0 `--fail-on high --only-fixed`: all four images exit 0
  (remaining research findings are Medium: CPython 3.12.16 binary CVEs and
  otel go-modules).
- scripts/check-image-lock-reconciliation.py, CI-exact args/members: engine
  126, hive 73, research 147, rsi 220 distributions — all OK.
- Both conductor identity-contract `docker run` verifications (security.yml
  argv, CPython 3.13.18) pass on the ordinary and observability images.
- `npm audit --audit-level=high` exits 0 on both frontend lockfiles (hive
  carries 7 moderate findings, below the configured threshold).
- Everything else green at this head: uv lock --check; check-image-pins
  (default + --base-digests); check-image-inventory; check-workflow-inventory;
  check-build-context; check-suite-inventory (21 suites, tests/: 6226);
  vulture ledger with CI argv (1238 reviewed = 1238 findings, base f8a2df966a);
  ruff check/format (driver logs); pytest tests/pi_recovery 177 passed + 32
  subtests; tests/test_devskim_scan_scope.py 21 passed; systemd-analyze --user
  verify on the four unit templates; no .py/test delta exists between
  a11908f338 and a79a689ae3, so the coverage gate's green evaluation at
  a11908f33 carries over unchanged.

Environment note for future rounds: the shared daemon host runs at 100% disk
(a prior attempt died to ENOSPC mid-build). grype/syft extract image layers
into $TMPDIR; /tmp is a 32G tmpfs that cannot hold the 4.6GB research image —
export TMPDIR onto the large filesystem before scanning research/rsi, and
expect a failed `no space left on device` grype leg to be an environment
limitation, not a finding. The SBOM/license (syft) leg was not re-run locally
for the same reason; every dependency this branch ships is Apache/MIT/BSD, so
no policy-relevant license class changed. The "recovery budget exhausted:
openrouter poolside/laguna-s-2.1:free 404" block in the lane brief is agent-
orchestration infrastructure, not a repository defect.

## Develop sync f927334a2 completed + all gates re-proven at merge f8aa5ad4f9 (2026-11-16, verified round)

The lane's blocked state ("worker exited without result") was an interrupted
develop sync: the prior round had ported origin/develop's content (M1-E2
157c3f61 #1373 + M2-B1 f927334a2 #2241 and their CR1373 CI repairs) into the
worktree staged but uncommitted, and died before the merge commit. This round
completed it in two commits:

1. `07b439b293` — the salvaged port committed verbatim. Every shared file was
   sha256-verified byte-identical to origin/develop before committing, except
   the three files carrying this branch's own repair state (hive Dockerfile
   npm audit-level line, pyproject supply-chain floors, uv.lock re-lock).
2. `f8aa5ad4f9` — `git merge origin/develop` (parents 07b439b293 + f927334a2e),
   auto-resolved with zero conflicts because the port had pre-aligned the tree;
   branch floors (temporalio>=1.36.1, graphql-core>=3.3.1, oauthlib, pyasn1,
   pypdf, soupsieve, patchright, playwright, dnspython, joserfc,
   opentelemetry-api) and npm audit-level lines all survived, `uv lock --check`
   exit 0, locked versions at/above every fix version (temporalio 1.36.1,
   graphql-core 3.3.2, dnspython 2.9.2, joserfc 1.8.0, otel-api 1.45.2,
   oauthlib 4.0.1, pyasn1 0.6.5, pypdf 7.1.0, soupsieve 4.1.1, patchright
   1.64.4, playwright 1.65.2). The merged uv.lock is byte-identical to
   develop's, and packages/ Python is byte-identical to develop's — the only
   branch-unique deltas vs develop are scripts/pi_recovery, tests/pi_recovery,
   the npm audit-level lines/lockfiles, the four constraint floor blocks, and
   inventory notes.

Local proof at f8aa5ad4f9, CI's exact commands:

- Coverage gate: root producer (`coverage run --branch --source=scripts -m
  pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q`, RATCHET_BASE_REV=origin/develop) -> 6109 passed / 139
  skipped / 0 failed in 14m33s; `coverage xml`;
  `scripts/check-diff-coverage.py coverage.xml --base origin/develop` -> exit 0
  (9 measured scripts/pi_recovery modules >=90% lines / >=80% branches, 7
  exempt test files). Publish-set floor (87%) structurally unaffected:
  `git diff HEAD origin/develop -- packages/maistro-{core,canvas,evolve,rsi,
  bootstrap}` Python is empty (only canvas frontend lockfile/.npmrc differ —
  not in any measured tree).
- Vulture ledger, CI argv (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1236 reviewed identities == 1236 findings, base
  resolved to f927334a2e (develop's M1-E2 removed 2 identities from the
  ledger's scope; count moved 1238 -> 1236 with the sync, not with this round).
- Suite inventory: ok, 21 suites match the recorded baseline; ruff check +
  format --check clean; tests/pi_recovery + test_devskim_scan_scope +
  test_check_diff_coverage: 216 passed + 32 subtests.
- Image gates offline: check-image-pins (9 pins/10 Dockerfiles), 
  check-image-inventory (2 PUBLISHED / 4 DISTRIBUTED / 3 INTERNAL), 
  test_distribution_contract + test_pinned_digest_references (14 passed), and
  all four CI `uv export --locked` reconciliations produce hash-pinned exports.
- Container gate, bounded local evidence: build inputs for every scanned image
  are byte-identical to develop tip f927334a2e (Dockerfiles, uv.lock,
  image-pins.json), which landed through its own merge-queue evaluation of
  this gate. Supplementary: the daemon's fresh `pr-1640` image set (built
  minutes earlier by a concurrent lane from a develop-based tree, content
  probes confirm CPython 3.13.18 in engine and temporalio 1.36.1 in
  rsi-runner — exactly this branch's locked content) scanned clean with CI's
  trivy argv (v0.73.0, HIGH/CRITICAL, ignore-unfixed, .trivyignore.yaml):
  maistro-engine exit 0, maistro-rsi-runner exit 0. Provenance caveat: pr-1640
  images were not built from this worktree; docker CLI rebuild (29.9.3 +
  x/net 0.62.0 patch) and hive/research images rest on the byte-identity
  argument plus the a79a689ae3-round 4-image proof. Full local rebuild was
  skipped: / at 99% (15G free) and trivy's shared DB cache was held by the
  concurrent lane — the same environment class a3f491e718 documented.
- npm audit --audit-level=high exit 0 on both frontend lockfiles (canvas 0
  findings; hive moderate-only, below threshold).

## Round 2026-11-17 (head 0a5e94f0ba): semgrep .npmrc repair + e2e-ui flake triage

Lane brief named "Container scan + SBOM + cosign: failure" from board accounting at
a11908f33 — stale: the check-runs snapshot for head 0a5e94f0ba (captured
2026-11-17T05:42Z) shows that check **success** (completed 05:34:12Z), as re-proven
by the a79a689ae3 round. The actually red checks at this head were:

1. `SAST / Semgrep` (job 133836349621) — reproduced locally with CI's exact argv
   (`uvx semgrep --metrics off --config tools/semgrep/maistro-rules.yaml --config
   p/security-audit --config p/owasp-top-ten --config p/secrets --exclude
   'packages/hive-conductor/eval' --exclude 'packages/hive-conductor/cage' --error
   packages/ tests/`): 2 blocking findings, rule
   `npm-missing-minimum-release-age`, on the two `.npmrc` files the a11908f33
   audit-level fix created (`packages/hive-conductor/frontend/.npmrc`,
   `packages/maistro-canvas/frontend/.npmrc`). Fix (this round): add
   `min-release-age = 7` to both, exactly what the rule's message requires.
   Re-run of the same argv after the edit: **0 findings, exit 0** (366 rules,
   2272 files). `SAST (bandit + semgrep + gitleaks)` is the aggregate job and
   clears with Semgrep; Bandit and Gitleaks were already success at this head.
   npm-compat: CI installs run node 22 (npm 10.x), which ignores the unknown
   key (`npm config get min-release-age` -> 7, parses clean; Dockerfile `npm ci`
   runs before the .npmrc is copied, so image builds are untouched).
2. `hive-conductor-e2e-ui` (job 133837655112) — failed in
   `tests/e2e/rsi-polling-resilience.spec.ts:459` ("a prolonged outage backs off
   exponentially"), identically on attempt AND retry: `Expected <= 10, Received:
   1000`. Triage: the branch's delta vs develop touches no frontend source and no
   spec — only build-tool patch bumps in the frontend lockfiles (@babel/*,
   esbuild 0.28.x) — and develop CI at the same frontend code is green
   (run 43939149467, job 133551910963, 2026-11-16T19:25Z), as is a concurrent
   merge-queue run for a different PR (run 44022926558, 2026-11-17T05:16Z, minutes
   before ours). The test itself documents the race class: it assumes a 200ms
   real-time settle always lands the aborted fetch before the next fake-clock
   chunk arms the backoff timer; a mid-chunk settle re-anchors the deadline and
   yields exactly this off-by-thousands signature. playwright.config.ts already
   records ("the failures it throws are environmental, not product regressions").
   Local proof on THIS branch's built compose stack: full rsi spec 8/8 passed
   (1.1m), then the exact failing test 2 more times (9.5s, 9.7s) — 3/3 green with
   the branch lockfile content.
3. `integration-scope` (job 133836349046) — log line: `hive-conductor-e2e-ui is
   required by integration scope but concluded failure`; pure downstream
   aggregator of (2), no independent defect.

Round changes: the two `.npmrc` lines above + this note. No Python, gate, ledger,
lockfile, or test change; no test added, so no inventory-note delta. Battery:
ruff check clean, ruff format --check clean (3584 files), semgrep CI-argv 0
findings, failing-spec local repro 3/3 pass.

## Free-router resolve narrowed to OpenRouter-owned picks (2026-11-17, salvage round)

Salvaged the interrupted prior round's uncommitted fix (left at head 9d8a6baf24
after a pre-worker `ruff format --check` failure) and completed it:

- `resolve_concrete_free_model` now degrades to None for any served pick that
  is not OpenRouter-owned (`openrouter/…`): a third-party `:free` pick 404s
  once its provider un-free's the model (the longcat
  `nous/meituan/longcat-2.5-preview:free` incident that exhausted a run's
  recovery budget), so resolution must fall back to DEFAULT_FREE_MODEL.
- New regression test pins the exact incident model → None (proven to fail
  against the pre-fix code, which returned the dead model); happy-path fixture
  updated to an OpenRouter-owned id. Inventory delta
  `packages/maistro-rsi/tests: +1` recorded in
  `docs/testing/inventory-notes/1896-free-router-openrouter-owned-resolve.md`.
- Local proofs at the round head: `ruff check .` and `ruff format --check .`
  pass (3584 files); `pytest packages/maistro-rsi/tests` 1795 passed / 2
  skipped; suite inventory rsi suite ok (1798); vulture ledger with CI's exact
  argv 1236 == 1236 (base f927334a2e). The one local-only failure,
  `test_contained_fitness.py::test_real_container_runs_the_vector_…`, is the
  docker-gated real-container case failing because the local builders image
  lacks pytest inside (`No module named pytest`) — CI has no docker daemon so
  that case skips there and cannot gate this branch.

## Round 2026-11-17 (merge c2a3025142): develop sync d0e8e235a8 (node 26-alpine #2120)

Salvaged the interrupted develop-sync merge left in the worktree at starting head
df1e4ef6 (MERGE_HEAD d0e8e235a8, 11 files already staged as resolutions, two
package-lock.json conflicts unresolved). Completed it:

- Lockfile conflict resolution took develop's side for both
  `packages/hive-conductor/frontend/package-lock.json` and
  `packages/maistro-canvas/frontend/package-lock.json`, proven non-regressive by
  package-by-package version comparison: same dependency set (package.json
  byte-identical on both sides vs merge base 809f84c8a6), HEAD-newer count = 0,
  develop-newer counts 27 (hive) / 93 (canvas); the a11908f338 audit fixes
  (canvas minimatch 11.0.8) are present on both sides. Conflicted worktree state
  backed up to `../cr1896-unmerged-snapshot.patch` before resolving.
- `packages/hive-conductor/Dockerfile` is a true content merge: develop's
  `FROM node:26-alpine@sha256:40cd011b…` (pin registered in its
  quality/image-pins.json row, merged verbatim) plus the branch's
  `npm config set audit-level=high &&` prefix retained.
- All other develop-side files verified byte-identical to d0e8e235a8 after the
  merge (empty diff); quality/ row counts unchanged vs develop
  (`git diff --numstat d0e8e235a8 -- quality/` empty).
- Previous-round "recovery budget exhausted: provider error
  (nous/stepfun/step-3.7-flash:free): 400 missing tags" block was model-provider
  infrastructure, not repo state: all 5 checks that ran at df1e4ef6
  (uv sync, ruff check, ruff format, pytest test_free_router.py, suite inventory)
  passed (jobs/435bb3b1…/result.json).

Gate proofs at the merged head c2a3025142:

- vulture ledger, CI's exact argv (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1236 reviewed == 1236 findings, candidate c2a3025142
  against base d0e8e235a8, 0 unclassified.
- `scripts/check-image-pins.py`: 9 pinned images across 10 Dockerfiles, all
  registered — validates the node:26-alpine row merged from develop.
- `scripts/check-image-inventory.py`: OK, 9 Dockerfiles inventoried.
- ruff check + ruff format --check: clean (3587 files).
- pytest tests/test_prepull_base_images.py tests/test_check_image_pins.py
  tests/test_pinned_digest_references.py packages/maistro-rsi/tests/test_free_router.py:
  99 passed. Suite inventories ok with no delta needed:
  packages/maistro-rsi/tests 1798, tests/ 6230 — no inventory note required
  (no test added or removed).
- Docker proof of the merged lockfile in CI's exact context:
  `docker build -f packages/hive-conductor/Dockerfile --target frontend` on
  node:26-alpine@sha256:40cd011b… runs `npm config set audit-level=high &&
  npm ci` + vite build green (image exported, then removed).
- Container-scan gate analysis: the job (security.yml) is image-level only —
  4 buildx builds, trivy HIGH/CRITICAL with ignore-unfixed, grype --only-fixed,
  syft, cosign. No npm audit step exists in it or in any current Dockerfile
  (the a11908f33-era `npm audit` build step was removed by a79a689ae; current
  hive Dockerfile line 15 only sets audit-level for npm ci, which does not
  audit). The merged picomatch/tinyglobby/fdir dev toolchain never ships in a
  final image (final stages copy dist/ + backend venv), and the advisory is
  unfixed anyway, so both trivy (ignore-unfixed) and grype (--only-fixed)
  structurally cannot fail on it.
- NEW upstream environmental finding, documented not repaired:
  `npm audit --audit-level=high` now exits 1 on BOTH frontends (canvas 6 high,
  hive 5 high + 6 moderate) — picomatch ReDoS GHSA-fc5q-39xc-vjpf /
  CVE-2026-112366, vulnerable range `<= 4.0.7` with `patched_versions: None`
  (latest release 4.0.7 predates the advisory), advisory DB updated
  2026-11-17T15:56Z. Verified identical failure at the PRE-merge head df1e4ef6
  (audit against its canvas lock: same rc=1), so this round did not introduce
  it — every branch and develop itself (identical locks) now fails this step.
  npm's suggested fix is a breaking multi-major downgrade (canvas vitest
  ^5.0.0 → 3.1.4, hive vite 6.3.x → 6.2.7); not actionable as a minimal CI
  repair, and no in-tree exception mechanism exists for the plain
  `npm audit --audit-level=high` step (ci.yml:702) short of weakening the gate.
  Left red pending an upstream picomatch patch; flagged for the next round.

## Round 2026-11-18 (head a7da3a4917): verification round — brief-named gate
resolved, npm-audit block re-proven external and still unpatched

Lane brief named "Container scan + SBOM + cosign: failure" (board accounting at
a11908f33) and "Previous block: recovery budget exhausted (provider 404)".
Both are stale/resolved at this head:

- Check-runs snapshot for a7da3a4917 (fresh API read 2026-11-18, plus the
  capture in jobs/a2bf0b80091f…/dispatch-context.json): `Container scan +
  SBOM + cosign` completed **success** (security workflow run 44214879080,
  job 134502096573), `Coverage gate (publish-set floor + diff coverage)`
  completed **success** (run 44214877091, job 134509189354 — the PRIOR
  ATTEMPT HISTORY's red gate), `security`,
  `exact-debt-ledger`, `Quality / Vulture`, `workflow-lint` and every Quality
 /* job success. The provider-404 run-block was repo-side fixed by c4ae258ae0
  (OpenRouter-owned resolve) — driver checks at this head: uv sync ok, ruff
  check ok, ruff format --check ok (3587 files), pytest
  packages/maistro-rsi/tests/test_free_router.py 22 passed, suite inventory
  packages/maistro-rsi/tests ok (1798).
- The actually red check at this head is **`test` (conclusion failure, job
  134502090130, run 44214877097, completed 2026-11-18T01:31:14Z)**. Full job
  log read: every Python suite green (server 659 passed / 11 skipped, turing
  225, turing-backend 138, design 662, ext-harness 273, ext-sdk 147, root
  tests/ 5997 passed / 140 skipped / 32 subtests, conductor backend + both
  frontend lint/build/test:ci green); the job fails in its LAST step,
  `npm audit --audit-level=high` (ci.yml:702, working-directory
  packages/maistro-canvas/frontend): picomatch GHSA-fc5q-39xc-vjpf, 6 high.
  The two "Event loop is closed" annotations are aiosqlite thread warnings
  (PytestUnhandledThreadExceptionWarning) under test_webhooks.py — warnings,
  not failures.
- Fresh upstream state verified 2026-11-18 (do not re-litigate without a new
  fact): registry `npm view picomatch` latest = **4.0.7** (published
  2026-08-24, predates the advisory); advisory GHSA-fc5q-39xc-vjpf
  `patched_versions: None`, vulnerable range `<= 4.0.7` (= every released
  version), updated 2026-11-17T15:56:44Z; fdir 6.5.0 depends on
  `picomatch ^4.0.4`, so every resolvable tree member is vulnerable. npm's
  "fix available: vitest@3.1.4 (breaking)" is contradictory output — no
  picomatch version escapes the range, so the only audit-clean trees contain
  no picomatch at all.
- Not introduced by this branch, proven: `git diff origin/develop..HEAD --
  packages/maistro-canvas/frontend/ packages/hive-conductor/frontend/package-lock.json`
  = `.npmrc` +2 lines only (the 0a5e94f0ba semgrep fix); both lockfiles and
  package.json byte-identical to develop, and the six vulnerable-path
  versions (picomatch 4.0.7, fdir 6.5.0, tinyglobby 0.2.17, vitest 5.1.0,
  vite 8.3.8, @vitejs/plugin-react 6.3.0) match develop exactly. Local
  `npm audit --audit-level=high` at this head reproduces CI's report
  verbatim (6 high). Develop's last GREEN merge-group run of ci.yml
  (d0e8e235a8, 2026-11-17T09:31Z) predates the advisory-DB refresh
  (15:56Z) — develop tip now fails the same step identically. The branch
  cannot enqueue until upstream patches picomatch or policy re-scopes the
  audit step; both are outside this lane's authority (no gate weakening).
- Issue acceptance re-proven at this head: `tests/pi_recovery` 177 passed +
  32 subtests (85 issue-sanctioned cases from pi-foremen-recovery.md + 92
  coverage-repair cases from pi-foremen-recovery-coverage.md, both notes
  carry `inventory-delta:` front-matter); root suite inventory ok (6230
  identities, matches recorded baseline); driver checks above. No source,
  gate, ledger, lockfile or test change this round; documentation only, so
  no inventory-note delta.

## Round: re-verification at `06fa24df46` (2026-11-18, job 6a0df02ecb)

Dispatched after the BLOCKED round above to re-verify acceptance and check
whether the external npm-audit block moved. **It has not.**

- Upstream re-checked fresh: registry latest picomatch = 4.0.7 (unchanged,
  2026-08-24); advisory GHSA-fc5q-39xc-vjpf still `vulnerable <= 4.0.7` with
  **no patched version listed**, not withdrawn. origin/develop tip unchanged
  (`d0e8e235a8`), so no sync is possible or needed.
- CI at the pushed head `a7da3a4917` unchanged: every workflow success except
  `CI` run 44214877097, whose only red step is `npm audit --audit-level=high`
  (ci.yml:702). Local reproduction: exit 1, 6 high (picomatch chain via
  fdir/tinyglobby/vite — dev tooling only). No non-weakening in-tree fix
  exists (no fixed version to pin; `audit fix --force` is a breaking vitest
  downgrade). Blocked on upstream or a policy-owner re-scope, as before.
- Acceptance re-proven at this head (all deterministic, all green):
  - `uv run pytest tests/pi_recovery -q` → 177 passed + 32 subtests.
  - `uv run python scripts/check-suite-inventory.py --suite tests/` → ok,
    6230 identities match the recorded baseline; both inventory notes carry
    `inventory-delta:` front-matter (+85 / +92).
  - `uv run ruff check .` → pass; `uv run ruff format --check .` → pass
    (3587 files).
  - `uv run python scripts/check-vulture-baseline.py packages/*/src
    --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1236
    identities match the reviewed ledger).
  - `systemd-analyze --user verify` on all four systemd templates → OK.
  - `uv run pytest packages/maistro-rsi/tests/test_free_router.py -q` →
    22 passed (provider-404 resolve fix).
  - Authority/privacy scan: no credential-shaped strings in tracked
    `scripts/pi_recovery/` sources (all matches are policy text such as
    "never credentials"); no 32+ hex session-id lookalikes; no absolute
    host paths outside `__pycache__` (untracked, 0 pycache in the diff);
    branch diff vs develop = 38 files, frontends differ only by `.npmrc`.
- No tree change this round beyond this documentation record; no
  inventory-note delta (no tests added or moved).

## Round: unsatisfiability proof at `99d07cccf5` (2026-11-18, job 8dfe5a743)

Dispatched to fix the named red gate. Fresh dispatch context (37 API calls,
captured 2026-11-18T05:38Z) first corrects the brief: at the pushed head
`a7da3a4917` **"Container scan + SBOM + cosign" is green** — the check-run
census is 79 runs, 78 success, exactly 1 failure: `test` (job 134502090130,
run 44214877097), whose red step is `npm audit --audit-level=high`
(ci.yml:702, `packages/maistro-canvas/frontend`'s standalone audit). The
brief's named failure is stale board accounting from head `a11908f33`.

**New decisive evidence this round — the audit is unsatisfiable with ANY
released dependency set** (prior rounds asserted this; now proven empirically):

- Registry re-check fresh: picomatch latest is still 4.0.7 (2026-08-24).
  GHSA-fc5q-39xc-vjpf range is `<=4.0.7` — i.e. **every released picomatch
  version is in the vulnerable range**; tinyglobby is flagged `*` (all
  versions, via fdir `>=5.2.1` + picomatch); vite `>=6.3.0-beta.0` (all of
  6.3+/7.x/8.x) uses tinyglobby → picomatch. Any tree containing vite >=6.3
  or any picomatch fails the audit.
- Downgrade experiment (npm's own `fixAvailable` suggestions: vite 6.2.7,
  vitest 3.1.4, @vitejs/plugin-react 5.2.0), run in an isolated scratch copy
  with a fresh lockfile: the audit gets **worse**, not better — 7
  vulnerabilities (1 moderate, 4 high, 2 **critical**: tinypool `<=2.1.1`
  GHSA-5gmw-xhrv-c9v3 / GHSA-85c8-ppgw-ccpr; plus the vite `<=6.4.3`
  advisory pile, fix 6.4.6 — which re-enters the picomatch chain). Exit 1.
- Version-lattice conclusion: vite `<6.3.0-beta.0` → covered by the
  `<=6.4.3` advisories; vite `>=6.3.0-beta.0` → picomatch chain. vitest
  `>=3.1.2` → picomatch chain; vitest `~3.1.4` → critical tinypool. No
  clean vite and no clean vitest exist today. `npm audit
  --audit-level=high` for this package therefore cannot pass until upstream
  ships patched picomatch/tinyglobby (and the vite/tinypool lines for any
  hypothetical downgrade path). Removing vite/vitest or `--omit=dev` would
  be a gate weakening or a toolchain rewrite — out of scope.
- Block not branch-introduced: `origin/develop` canvas frontend pins are
  byte-identical (`vite ^8.1.6`, `vitest ^5.0.0`, `@vitejs/plugin-react
  ^6.0.1`) — develop fails this step identically. Local reproduction at
  this head: exit 1, metadata 0 info / 0 low / 0 moderate / **6 high** /
  0 critical (picomatch chain only: fdir 6.5.0, tinyglobby 0.2.17,
  picomatch 4.0.7 — dev tooling).
- Driver ran no deterministic checks this round (manifest `checks: []`, no
  `check-*.log` in the job dir); all validation below self-executed.

Acceptance battery re-proven at `99d07cccf5` (all deterministic, all green):
`uv run pytest tests/pi_recovery -q` → 177 passed + 32 subtests;
`uv run pytest packages/maistro-rsi/tests/test_free_router.py -q` → 22
passed; `uv run python scripts/check-suite-inventory.py --suite tests/` →
ok (matches recorded baseline); `uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` → 1236 identities match; `uv run ruff check .`
→ pass; `uv run ruff format --check .` → pass (3587 files). No tree change
beyond this record; no tests added or moved, so no inventory-note delta.

**Required next action is outside this lane:** upstream patched releases
(picomatch/tinyglobby lockfile bump) or a policy-owner re-scope of the
standalone audit step (ci.yml:702). Escalated as NEEDS-DEEP-REVIEW.

## Round: external audit block dissolved — verified green at PR head `4928a1e4d1` (2026-11-25, job 44172cfff4d9)

Prior job `882b01594b44` at the same starting head `c63ad95ff` passed all five
driver checks (uv sync, ruff check, ruff format, `test_free_router.py` 22
passed, suite inventory) and then died from a provider 404 before producing a
verdict; the worktree was clean, so no tree work was lost.

**The npm-audit block has moved — in our favor.** The GHSA-fc5q-39xc-vjpf
(picomatch ReDoS) advisory was **withdrawn** (`withdrawn_at: 2026-11-18T15:38:56Z`,
per the in-tree CR-2375/CR-2377 notes) **without any upstream fix**:
`npm view picomatch version` → 4.0.7 (still the newest release, still inside
the withdrawn advisory's `<=4.0.7` range; tinyglobby 0.2.17 and fdir 6.5.0
unchanged). npm's audit database stopped reporting it, so the identical
committed lock that audited 6-high on 2026-11-18 now audits clean. Develop
itself resolved the fallout by adding `scripts/npm_audit_gate.py` (two-way
ratchet), retiring the stale waiver, and pinning `ALLOWED == {}` in
`tests/test_npm_audit_gate.py` — all of which this branch now carries through
the develop merges.

Local branch fast-forwarded `c63ad95ff` → `4928a1e4d1` (origin/ops branch =
PR #1896 head; two develop merges `e38685add9` + `4928a1e4d1`). The
branch-unique surface vs its develop parent (`3ae2971366`) is unchanged:
the `scripts/pi_recovery/` port, `tests/pi_recovery/`, ops docs and the
earlier CI repairs — no product-package changes of its own.

Fresh reproduction at `4928a1e4d1`, CI's exact commands, all green:

- Canvas audit leg (ci.yml:714-716): `npm audit --json > /tmp/npm-audit.json
  || true` then `python scripts/npm_audit_gate.py /tmp/npm-audit.json` →
  `npm audit OK (0 advisories reported, all triaged in ALLOWED)`, exit 0.
  `npm audit --audit-level=high` standalone → `found 0 vulnerabilities`, exit 0.
- `uv run pytest tests/test_npm_audit_gate.py -q` → 15 passed (includes the
  shipped-state pin `ALLOWED == {}`).
- security.yml "Build frontend license surfaces" sequence, both frontends:
  `npm config set audit-level=high && npm ci && npm run build` → exit 0
  (canvas: `found 0 vulnerabilities`; hive-conductor: 7 moderates only,
  below the high threshold; both vite builds succeeded). This is the same
  npm surface as hive-conductor `Dockerfile:15`'s
  `RUN npm config set audit-level=high && npm ci`.
- Vulture ledger (CI args) at `4928a1e4d1`: 1235 reviewed identities →
  1235 findings, exit 0. The −1 row vs the previous round comes from
  develop's own `_vulture_whitelist.py` banking merged from develop — no
  branch-side ledger edit this round.
- Full battery: `uv sync --locked --extra dev` ok; `uv run ruff check .` →
  pass; `uv run ruff format --check .` → pass (3602 files);
  `uv run pytest tests/pi_recovery -q` → 177 passed + 32 subtests;
  `uv run pytest packages/maistro-rsi/tests/test_free_router.py -q` →
  22 passed; `uv run python scripts/check-suite-inventory.py` → ok
  (21 suites match the recorded inventory).

No tree change beyond this record; no tests added or moved, so no
inventory-note delta. The named container-scan gate was already green at
`a7da3a4917` (stale board accounting), and the last red audit leg is green
with the registry's current advisory data.

## Round 2026-11-25 (start head `bf0d534702`, job `c73ac0bde467`): branch-caused `RUN npm ci` regression fixed; the remaining red is develop's expired #313 exemption

**The previous two jobs never measured anything — the venv was root-owned.**
Jobs `0cd7ac590a9a` (verify) and the first pass of this one died on their very
first driver check with `error: failed to remove directory
/home/dev/Git/wt/cr-1896/.venv/lib: Permission denied (os error 13)`
(`check-0.log` in both job dirs): a container run had recreated `.venv/` as
`root`. Ownership restored with `sudo chown -R dev:dev .venv` — no tracked
content touched, nothing discarded. Every check below then ran for real.

**Driver checks, green (all with CI's exact arguments):**

- `uv sync --locked --extra dev` → exit 0
- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 3670 files already formatted
- `uv run pytest packages/maistro-rsi/tests/test_free_router.py -q -x` → 22 passed
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-rsi/tests` → ok (1798 identities)
- `uv run python scripts/check-suite-inventory.py` → ok, 21 suites / 36661 node IDs / 0 duplicate evidence
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1221 reviewed identities → 1221 findings, exit 0. The brief's ledger-amendment path is **moot at this head**: nothing is unbanked, so `quality/vulture-baseline.json` was not touched.
- `uv run pytest tests/pi_recovery -q` → 177 passed + 32 subtests

**Live CI at `bf0d534702` (read-only `gh pr view … statusCheckRollup`), final tally 78 success / 3 failure.**

The brief's named failure is stale board accounting. `Container scan + SBOM +
cosign` → **COMPLETED SUCCESS** at this head; the `failure` in the dispatch
came from `a11908f338` (2026-11-16). That old job's own log (job
`133159928643`) shows the quoted npm lines were incidental: step `#25 RUN npm
config set audit-level=high && npm ci` printed `7 moderate severity
vulnerabilities` / `Run npm audit for details.` at 51.58s and **continued**;
the job died nine minutes later after Trivy's vulnerability tables
(`##[error]Process completed with exit code 1`, log line 13708). Develop has
since carried the Trivy suppression (`0282be2423`) through the merge. Also
green at this head: `docker-build`, `docker-rebuild-compare`,
`integration-scope`, `hive-conductor-e2e`, `hive-conductor-e2e-ui`, `JS supply
chain (npm audit + GuardDog + policy gate)`, `Quality / Vulture`,
`exact-debt-ledger`, `SAST / Semgrep`, `Supply chain (pip-audit)`, `Gate C —
canonical clean install`, `coverage (MinIO)`.

Red: `lint-and-type-check`, `test`, `Coverage gate (publish-set floor + diff
coverage)`. All three reduce to the same four test failures plus one gate step.

**Fixed this round (`d7a5303b33`) — `tests/test_js_dependency_gate.py::TestTheRealRepo::test_builds_reconcile_to_the_audited_lockfiles`, `assert 'RUN npm ci' in dockerfile`.**

Branch-caused, and nine commits old: `a11908f338` rewrote the image's install
step as `RUN npm config set audit-level=high && npm ci`. The JS supply-chain
gate asserts every build path installs lockfile-exact with the literal
`RUN npm ci` (and never `npm install`), so prefixing the command broke the
assertion without changing what the install does. The repair keeps the gate
exactly as written and keeps the intent: `RUN npm ci --audit-level=high`. No
threshold moved — a moderate advisory still does not fail an image build,
high/critical still does, and `scripts/npm_audit_gate.py` still owns the
advisory verdict on the committed lockfiles.

Proof: `uv run pytest tests/test_js_dependency_gate.py -q` → 38 passed;
the four other suites that read this Dockerfile with it
(`tests/test_prepull_base_images.py`, `tests/test_prepull_copy_sources.py`,
`tests/test_image_lock_contract.py`, `tests/test_check_build_context.py`) →
184 passed; `docker build --target frontend -f
packages/hive-conductor/Dockerfile .` → exit 0, vite bundle built; inside the
pinned `node:26-alpine@sha256:40cd011b…` (npm 11.20.0) `npm --audit-level=high
config get audit-level` → `high` and `npm ci --audit-level=high` is accepted.

**Not this branch — the two `tests/test_check_public_routes.py` failures and `lint-and-type-check`'s `scripts/check-public-routes.py` step are one finding.**

`/v1/auth/register` and `/v1/setup/` carry `disposition: temporary`,
`issue: 313`, `expires: 2026-11-24` in `quality/public-routes.json`, and today
is 2026-11-25. Proof it is base-inherited and purely calendar-triggered:

- `git diff 221dc3d517...HEAD -- quality/` is empty, and `git show 221dc3d517:quality/public-routes.json | diff - quality/public-routes.json` → identical. `origin/develop` *is* `221dc3d517` right now, so develop carries the same expired dates.
- Calling the gate's own `audit_registry()` over the shipped registry and middleware with a forced date: `today=2026-11-23` → 0 failures, `2026-11-24` → 0 failures, `2026-11-25` → exactly these 2. Nothing but the calendar moved.

Every branch in the repository, develop included, fails `lint-and-type-check`
and the root suite from 2026-11-25 until the exemption is closed or
re-justified. The gate names both remedies; neither is this lane's to pick.
#313 ("[M2-A] Close public self-registration after initial setup") is OPEN, P1,
milestone M2, unassigned, and its acceptance criteria (durable race-safe
registration state, invite/admin-only after setup, exactly-one-owner under
concurrency) live in hive-conductor's authorization path — not in an ops PR
about Pi session recovery. And `quality/public-routes.json` is a security
allowlist ledger (`docs/ci/RATCHET-PROVENANCE.md:34`); this lane's brief
authorizes ledger amendment only for the vulture exact-debt ledger. Moving
`expires` forward on two `risk: high` unauthenticated write paths is a
route-owner decision (@BlakeMatthews-dev), and spending that forcing function
silently inside PR #1896 is exactly what the gate exists to prevent.
Escalated, not edited.

**Not this branch — `tests/test_prod_postgres_probe_live.py::test_first_boot_ready_only_after_init_completed`.**

Two different timing symptoms in two different jobs on the same head: the
`test` job (job `139042378028`) reported `never observed the temporary-server
window (socket accepting, TCP refusing); the scenario is inconclusive`, and the
Coverage gate's root-suite producer (job `139050831754`, `--timeout=30`)
reported `Failed: Timeout (>30.0s) from pytest-timeout`. The test polls a
widened 8-second init window at 0.5s granularity through two `docker exec`
probes per iteration, and its own inventory note
(`docs/testing/inventory-notes/2396-prod-pg-probe.md`) records it as
integration scope whose window is *measured*. This branch touches no `deploy/`,
compose, postgres or probe code. Reproduced green 3/3 locally against the same
pinned `pgvector/pgvector:pg17`: 13.48s, 13.75s, 13.77s.

**The Coverage gate did not fail on coverage.** Its publish-set aggregate
printed `TOTAL 95359 5415 25334 1858 93%` — above the 87% floor — and the job
then died in the non-publish `--source=scripts` producer on the same 4 test
failures (`4 failed, 6253 passed, 141 skipped`), before the diff-coverage step
ran. That step was reproduced locally instead, from a deliberately
*conservative* subset of CI's producers (`coverage run --branch
--source=scripts -m pytest tests/pi_recovery`, `coverage run --branch
--source=packages/maistro-rsi/src/maistro_rsi -m pytest
packages/maistro-rsi/tests`, combined, `coverage xml`):
`uv run python scripts/check-diff-coverage.py <xml> --base 221dc3d517` →
`ok: every measured file this change touches is at or above 90% lines / 80%
branch arcs`, exit 0 — 10 changed files measured, 7 exempt as test code,
all 9 `scripts/pi_recovery/` modules present in the report.

**Steps the short-circuit hid.** `check-public-routes.py` is `ci.yml:291`, so
three later steps of `lint-and-type-check` never ran in CI. Run here with CI's
commands: `scripts/check-closure-targets.py --body-file <PR body> --repo
Agent-StrongHold/Project-mAIstro` → `ok: PR body closes no issue by keyword`;
`scripts/check-shell-execution.py` → `ok: all 3 shell=True call(s) in the
governed trees are declared`; `scripts/check-build-context.py` → `ok: both
ignore files carry the same 60 rule(s), deny all 27 secret pattern(s), and
exclude nothing tracked`. Nothing else is red behind the expiry failure.

**What is left, and who owns it.** One tree change this round
(`packages/hive-conductor/Dockerfile`), no test added or removed, so no
inventory-note delta. After it lands, the only remaining blockers on this PR
are the repo-wide #313 expiry (owner decision on `quality/public-routes.json`,
or #313 itself) and the timing-sensitive prod-postgres live probe — neither
reachable from this lane without either a security-ledger edit it is not
authorized to make or a product authorization change it must not invent.

## Round 2026-11-25 (start head `727920edd2`, job `095dab865df6`): container gate re-proven at the live PR head, and the `uv.lock` revision downgrade proven inert

The brief again named **"Container scan + SBOM + cosign: failure"** — the same
`a11908f338`-era board accounting three rounds have now disproved. Read the
authoritative surface this time, not an inference: `gh api
commits/bf0d53470239…/check-runs` returns 81 check runs, 78 success / 3
failure, and `Container scan + SBOM + cosign` is **completed / success**. The
three red ones are `Coverage gate (publish-set floor + diff coverage)`
(job 139050831754), `lint-and-type-check` (139042378306) and `test`
(139042378028).

**Those three red checks are exactly four test failures, and only one is ours.**
Pulled both job logs (`gh api actions/jobs/<id>/logs`): the `test` job reports
`4 failed, 6138 passed, 141 skipped` and the coverage job dies in step 7
`combine` (its root-suite producer) on the same four ids —
`test_check_public_routes::test_it_agrees_with_the_middleware`,
`test_check_public_routes::test_main_passes_and_says_how_many`,
`test_js_dependency_gate::test_builds_reconcile_to_the_audited_lockfiles`,
`test_prod_postgres_probe_live::test_first_boot_ready_only_after_init_completed`.
The middle one is the `RUN npm ci` regression `d7a5303b33` already fixed, which
is why CI still shows it: that commit is local-only, never pushed. Attribution
of the other three: `git diff --stat 221dc3d517..HEAD -- quality/
tests/test_check_public_routes.py tests/test_prod_postgres_probe_live.py
scripts/check-public-routes.py` is empty — the branch touches none of them.

**Re-measured here rather than carried over.**

- `uv run pytest tests/test_check_public_routes.py -q` → 2 failed / 22 passed,
  and the gate names its own two remedies verbatim: "the exemption expired on
  2026-11-24 — close it (#313) or re-justify it with a new date…" for
  `/v1/auth/register` and `/v1/setup/`. `gh api issues/313` → **open**, P1, M2,
  unassigned. Not this lane's ledger and not this lane's authorization path.
- `uv run pytest tests/test_prod_postgres_probe_live.py -q --timeout=30` (CI's
  own producer bound) → **3 passed in 51.85s**, ≈17s per test. Two different
  CI symptoms (an inconclusive-window assert in `test`, a `>30s` pytest-timeout
  in the coverage producer) on a test that passes locally under CI's bound is
  runner latency, and the branch ships nothing that reaches `deploy/`.
- Container leg, built from THIS head rather than argued: `docker build --target
  frontend --no-cache -f packages/hive-conductor/Dockerfile .` → exit 0, the
  changed `RUN npm ci --audit-level=high` step executes and the vite bundle
  builds. This matters specifically because `d7a5303b33` edited that line *after*
  the successful container run at `bf0d534702`.
- **New finding, previously unexamined by any round:** `bf0d534702`'s
  regeneration left `uv.lock` at `revision = 3` while develop `221dc3d517` is at
  `revision = 5` (and re-encoded four `pyobjc-framework-*` markers to their
  logically equivalent simple form). That looks like a container-gate hazard —
  the job's `Reconcile installed packages to uv.lock` step compares image
  contents to `uv export --locked` — so it was tested, not assumed: all four of
  CI's exact export commands produce files byte-identical to base's (only the
  header command line differs), the exports are identical when run with CI's
  pinned uv **0.12.5** (`uvx --from uv==0.12.5 uv export --locked …`, rc 0) as
  with local uv 0.12.20, and `uv lock --check` passes under both. The downgrade
  is semantically inert and no gate reads the revision number; no re-lock was
  attempted, because rewriting all four reconciled images' lock to change one
  header line is churn with a real downside and no gate to show for it.
- Vulture with CI's argv (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → `1221 reviewed identities -> 1221 findings`, exit 0.
  Nothing is unbanked, so the brief's ledger-amendment permission is moot and
  `quality/vulture-baseline.json` was not touched.
- Offline image/supply-chain gates: `check-image-pins` (11 pins / 11
  Dockerfiles), `check-image-inventory`, `check-workflow-inventory` (33),
  `check-build-context`, `check-uv-setup` (74 steps at 0.12.5),
  `check-suite-inventory` (21 suites), `check-reachability` (1503 production
  modules, 82 unreachable, rc 0) — all green.
- npm legs at this head: canvas `npm audit --json` → `npm_audit_gate.py` "OK (0
  advisories reported)"; hive → "OK (1 advisories reported, all triaged in
  ALLOWED)" with metadata `7 moderate / 0 high / 0 critical`; and
  `pytest tests/test_npm_audit_gate.py tests/test_js_dependency_gate.py` → 53
  passed, plus the five suites that read this Dockerfile → 184 passed.
- Diff-coverage measured fresh here (producers `tests/pi_recovery` 177 + 32
  subtests and `packages/maistro-rsi/tests` 1794 passed / 4 skipped, `coverage
  xml`): `scripts/check-diff-coverage.py coverage.xml --base 221dc3d517` →
  "ok: every measured file this change touches is at or above 90% lines / 80%
  branch arcs", 10 measured files, 7 exempt as declared test code.
- Issue acceptance re-checked: `pytest tests/pi_recovery -q -rs` → 177 passed,
  32 subtests, **zero skips**; `systemd-analyze verify` clean on all four unit
  templates; `tests/pi_recovery/test_portability.py` carries 20 cases including
  the fresh-bindings-disabled, never-replace-existing, unsafe-operator-session,
  relocated-package and no-embedded-user-home guards the PR body claims.

**Two accuracy defects in the PR body, recorded for the reviewer, not
repaired here** (editing the body is a GitHub mutation this lane must not
make): it still says "85 unittest cases … 85 pytest cases plus 17 subtests" and
"No product-package/runtime changes". Both were true of the `cf4a562b` draft.
At this head the port carries 177 cases + 32 subtests across six root-suite
files (+92 per `docs/testing/inventory-notes/pi-foremen-recovery-coverage.md`),
and later CI-repair rounds did touch product/runtime files:
`packages/maistro-rsi/src/maistro_rsi/free_router.py` (+8, OpenRouter-owned
pick filter, covered by `test_resolve_rejects_third_party_free_picks`),
`packages/hive-conductor/Dockerfile`, the two frontend `.npmrc` files, and
`uv.lock`. A reviewer reading the body as an ops-only diff will be misinformed.

**Round tally:** 1 named failure checked → 1 disproved with live CI evidence;
0 in-scope defects left unfixed (the one branch-caused failure is fixed in
`d7a5303b33`, unpushed); 2 base-inherited blockers escalated; 1 new inertness
proof recorded; 2 PR-body accuracy defects flagged. No test added or removed, so
no inventory-note delta. Tree change this round: this record only.

## Round 2026-11-25 (start head `23e9af624bf5`, jobs `9347b7f835bd` verify + repair): both remaining CI reds reduce to one base-inherited live probe test — observation window widened, coverage-gate cap dodged via the probe's own opt-out, in-window assertion made race-free

**What was actually red at this head** (read from the authoritative surfaces,
not the brief): `commits/23e9af624bf5…/check-runs` = 81 runs with exactly two
non-green — `test` (failure, completed 10:07:59Z) and `Coverage gate
(publish-set floor + diff coverage)` (in_progress at capture). The brief's
named "Container scan + SBOM + cosign: failure" is already completed/**success**
at this head — disproved with live CI evidence, same as the prior round.

**The `test` job failure** (run 45589709595, job 139120350560): exactly one
FAILED case,
`tests/test_prod_postgres_probe_live.py::test_first_boot_ready_only_after_init_completed`
— "never observed the temporary-server window (socket accepting, TCP
refusing); the scenario is inconclusive". Evidence read before changing
anything: the identical content passed on develop's own run 45581547101 at the
merge base `d5eea943294b` and passes locally (13.7s, same
`pgvector/pgvector:pg17`); the branch's 36-file diff does not touch this test,
`deploy/docker-compose.prod.yml`, or `deploy/init-replication.sh`. Inherited
scaffolding too tight for a loaded runner, not a branch regression.

**The coverage-gate failure** (run 45589709654, job 139131975084, completed
10:44:43Z — observed live to conclusion): the combine step's root
scripts-producer failed on the SAME test with a DIFFERENT symptom —
"Failed: Timeout (>30.0s) from pytest-timeout" — the only failure in
"1 failed, 6256 passed, 141 skipped". That producer runs
`pytest tests/ --timeout=30 -q` against `--source=scripts`: docker run +
initdb + final boot consume 15-25s of the 30s cap under load, and the test
measures nothing the producer owns.

**Repairs** (`1902f357a7`, `fd05a7f84e`; no gate weakened, no assertion
removed):

- `tests/test_prod_postgres_probe_live.py`: appended init sleep 8 -> 30
  (widens only the observation scaffold; `start_period: 300s` in the compose
  contract keeps it unscored mid-window), deadline 90 -> 120, every observed
  (socket,tcp) pair recorded and named in the inconclusive assertion; the
  in-window "must stay not-ready" assertion now uses the health sample taken
  at iteration start instead of re-reading `_health()` after the probes,
  which raced the shipped 5s-interval check's first successful evaluation at
  window end (reproduced once locally: whole-module failure at 68.9s with
  timing consistent only with that assert; 3 later module runs pass at
  77-80s; a standalone poll trace shows dozens of clean in-window matches
  and health flipping only after the window closes).
- `.github/workflows/quality.yml` combine step: `MAISTRO_PROD_PROBE_DOCKER=0`
  — the probe module's own pre-existing skipif opt-out — so the
  30s-capped producer stops hosting a test that cannot honor the cap, while
  ci.yml's no-cap `test` leg keeps it at full strength
  (`test_unit_suite_execution_partition.py` pins that leg; still passes).
  The producer's pg-gated legs skipping in this job is an established
  pattern (141 skips in the failing run). Skips change no collected node ID.

**Local evidence**: 3 live cases pass 3x consecutively (77-80s, real
containers); `MAISTRO_PROD_PROBE_DOCKER=0 … --timeout=30` (exact combine
shape) = 3 skipped in 0.2s; actionlint 1.7.7 + shellcheck 0.10.0 (workflow-
lint's exact commands) clean; `check-workflow-inventory.py` (33) and
`check-workflow-write-safety.py` clean; `check-suite-inventory.py` 21
suites / 36661 unique identities, ok; exact-debt-ledger's three steps
(`check-ratchet-provenance`, `check-shipped-surface-truth`,
`check-vulture-baseline` with CI's exact args, 1221 = 1221, 0 unclassified)
all OK at candidate `fd05a7f84ef0`; ruff check/format clean.

**Round tally:** 1 brief-named failure checked -> 1 disproved (containers
gate green at this head); 2 real reds diagnosed to one inherited test with
two distinct mechanisms; both repaired; 1 intermittent local failure
attributed with mechanism-level evidence (health-sampling race) and fixed;
no test added or removed (node IDs unchanged -> no inventory-note delta).
Tree change this round: the test file, the combine env, this record.

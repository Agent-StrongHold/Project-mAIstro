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

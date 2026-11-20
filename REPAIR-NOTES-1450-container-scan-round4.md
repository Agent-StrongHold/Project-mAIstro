# Repair notes — issue #1450 round 4 (container-scan round 4 / supply-chain round 3)

Branch `auto-80`, head before this round: `ce02ebba9274` (develop tip `f8a2df966a1d`
already merged in 58138f673; merge-base HEAD..origin/develop equals `origin/develop`,
so no develop conflict remains).

## What was actually failing at `ce02ebba` (from the real CI check runs + job logs)

The merge-queue prompt named only `Supply chain (pip-audit)` — that is **stale**:
the check-run list captured at `ce02ebba` (2026-11-16T03:28–03:42Z) shows it
**SUCCESS**, and the trunk merge-group run of pr-2241 at 03:08Z that failed
pip-audit did so on exactly the four advisories commit `5065aa9` already fixed
(dnspython 2.9.0→2.9.2, graphql-core 3.3.0→3.3.1, joserfc 1.7.5→1.7.6,
opentelemetry-api 1.45.1→1.45.2 — fetched job log, job 133063604884). This
branch's lock carries all four fixes, and the CI-exact local gate re-proves it
green (below).

The three **real** failures at `ce02ebba` were:

1. `Container scan + SBOM + cosign` — the `Trivy scan maistro-engine-research
   (HIGH/CRITICAL only)` step failed: `Total: 13 (HIGH: 13, CRITICAL: 0)`,
   all in the image's Python METADATA set: oauthlib 4.0.0 (CVE-2026-49272 →
   4.0.1), pyasn1 0.6.4 (CVE-2026-119194/-119195/-119196/-119197 → 0.6.5),
   pypdf 6.21.2 (CVE-2026-119203…-119209 → 6.21.3/6.21.4), soupsieve 3.0.3
   (CVE-2026-126190 → 4.0.0). A new advisory wave landed in trivy's feed
   between the green `5065aa9` run (02:03Z) and this run (03:29Z); the go
   HIGHs fixed in round 3 stayed fixed (`usr/local/bin/docker │ gobinary │ 0`).
2. `hive-conductor-e2e-ui` — 1 test failed twice (base + retry):
   `rsi-polling-resilience.spec.ts:542` "first backoff step = interval·2¹ at
   pinned jitter" expected `|stamp − flipEnd − 7500| ≤ 10`, received exactly
   1000 both attempts. **Not branch-caused**: `git diff origin/develop...HEAD`
   touches zero files under `packages/hive-conductor/` or any frontend path,
   and the identical spec + frontend code passed in the pr-2241 merge-group
   runs at 03:01Z/03:16Z (those runs failed only their `security` job) and in
   this branch's own run at `5065aa9` (02:03Z, overall SUCCESS). The
   assertion anchors on Playwright fake-clock chunk semantics with a 10 ms
   slop — an environment-sensitive control loop, not a code property this
   branch changed. Transient; needs a re-run, not a code change on this PR.
3. `integration-scope` — aggregator; its log states the cause verbatim:
   `hive-conductor-e2e-ui is required by integration scope but concluded
   failure`. Follows #2.

## Fix

`uv lock --upgrade-package oauthlib --upgrade-package pyasn1
--upgrade-package pypdf --upgrade-package soupsieve` — oauthlib 4.0.0 →
**4.0.1**, pyasn1 0.6.4 → **0.6.5**, pypdf 6.21.2 → **7.1.0**, soupsieve
3.0.3 → **4.1.1**. All past the advisory fix versions, per the gate's own
policy ("upgrade when a fixed version exists; only ALLOWED triage when none
exists"). Only `uv.lock` changed — no `pyproject.toml` constraint needed
widening; the resolver rides past the fix versions exactly as round 2 did
(graphql-core 3.3.2, joserfc 1.8.0). All four are transitive (pypdf ←
browser-use; soupsieve ← beautifulsoup4 ← markdownify ← browser-use; oauthlib
← requests-oauthlib ← google-auth-oauthlib; pyasn1 ← pyasn1-modules ←
google-auth) and are imported nowhere in shipped code (grep: zero direct
importers under `packages/*/src`), and no CI lane imports the real
`browser_use` module (the browser-tool tests use `SimpleNamespace` fakes —
test_client.py:152), so the pypdf/soupsieve major crossings carry no
reachable production regression surface on this tree.

## Evidence (all executed locally this round at the repaired tree)

**Controlled trivy reproduction (CI-exact scanner, version and flags):**

- Control venv pinned to the OLD versions (oauthlib==4.0.0, pyasn1==0.6.4,
  pypdf==6.21.2, soupsieve==3.0.3), scanned with
  `trivy:0.73.0 rootfs --scanners vuln --severity HIGH,CRITICAL
  --ignore-unfixed --ignorefile .trivyignore.yaml`: **`Total: 13 (HIGH: 13,
  CRITICAL: 0)`** — the exact 13 CVEs from the CI failure table
  (CVE-2026-49272, -119194, -119195, -119196, -119197, -119203, -119204,
  -119205, -119206, -119207, -119208, -119209, -126190). CI's failure mode
  reproduced bit-for-bit.
- Repaired venv built from `uv export --locked --package maistro-server
  --extra observability --extra browser --no-dev --no-emit-workspace`
  (the research image's exact install contract, Dockerfile.research:84-87;
  3389-line export, oauthlib==4.0.1 / pyasn1==0.6.5 / pypdf==7.1.0 /
  soupsieve==4.1.1), same trivy invocation: **exit 0, zero findings** — every
  python-pkg METADATA row clean. Same DB generation as the failing run
  (2026-11-16).
- The containers job's own lock-reconciliation input is the same export
  (`uv export --locked --package maistro-server --extra observability
  --extra browser …` in security.yml:502-505), so the reconciler sees exactly
  this set.

**Supply chain (pip-audit), CI-exact at the new lock:** `uv sync --locked
--extra dev` → `uv pip freeze --exclude-editable` → `pip-audit --strict
--format=json -r` → `scripts/pip_audit_gate.py`: **exit 0** — sole remaining
advisory the reviewed `ecdsa PYSEC-2026-1325` ALLOWED pair; direct-dependency
usage OK (11 packages, 66 runtime deps, 4 reviewed dispositions).

**security job's other leg:** `scripts/check-dependency-namespaces.py` →
exit 0 (218 distributions, no unreviewed top-level namespaces).

**Compatibility of the bumps:** `packages/maistro-core/tests/tools/browser/`
+ `packages/maistro-server/tests/test_entrypoint.py` +
`test_import_surface.py` → **133 passed, 4 skipped**.

**Sandbox conformance untouched:** `packages/maistro-bootstrap/tests/
test_container_lane.py + test_container_sandbox.py +
test_container_sandbox_hardening.py` → **33 passed, 20 skipped** (skips are
the structural live-lane/platform gates documented in round 3; the live
rootless lane proof and CI `sandbox-conformance` SUCCESS at `ce02ebba` stand
unchanged — uv.lock version bumps do not touch the sandbox code paths).
`check-suite-inventory.py --suite packages/maistro-bootstrap/tests` → ok,
309 identities (no test-count change → no inventory-note delta required).

**Repo battery:** `ruff check .` all passed; `ruff format --check .` 3562
files formatted; CI-exact vulture gate
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → RC 0 (1238 reviewed identities = 1238 findings).
`git diff --numstat origin/develop -- quality/` → only the 3 intended
branch rows from prior rounds; this round changed no ledger.

## Issue #80 acceptance re-check (file:line anchors, all reachable in-tree)

- Escape suite coverage: filesystem `test_path_escape_blocked`
  (test_container_sandbox.py:145); network
  `test_agent_commands_cannot_reach_any_network_by_default` (:208);
  process/namespace/device/host-socket
  `test_process_namespace_devices_and_host_socket_are_not_reachable` (:540),
  `test_no_block_devices_reachable` (:673),
  `test_no_host_unix_sockets_visible` (:684); credential
  `test_container_environment_is_credential_default_deny` (:420); privilege
  `test_agent_execs_run_as_unprivileged_user` (:240);
  kernel-boundary/userns :610, :637, plus the fail-closed
  `test_sandbox_refuses_a_rootful_unmapped_daemon` (:714).
- Network/credential default-deny: :208, :420, and hardening
  `test_container_is_created_default_deny_offline` (:233),
  `test_denylist_covers_the_ambient_credential_surfaces` (:456),
  `test_container_env_is_home_and_nothing_else` (:493).
- Seed hygiene (no `.env`/`.git`/host secrets): sandbox :259, hardening
  :419 (host-side tar with index allowlist), :83–:206 (split-index
  allowlist, replaced-path refusal).
- Non-root unless justified + containment proven: hardening :250, :301,
  :329, :350, :385, :391 (only root exec is the pre-seed chown).
- Read-only / minimized writable scope: sandbox :482, hardening :273.
- Timeout/kill/cleanup/resource exhaustion: sandbox :564, :584, :593;
  hardening :521, :546 (cleanup at every transfer stage).
- CI conformance lane: ci.yml:741 `sandbox-conformance` — **SUCCESS** at
  `ce02ebba`; live rootless proof recorded in round 3.
- SECURITY.md cites the evidence: SECURITY.md:367–385 +
  docs/security/SANDBOX-SUPPORT-MATRIX.md.
- Same production backend: test_container_sandbox.py instantiates the real
  `ContainerBuilderSandbox` (module header, lines 1–13 — "not a fake or a
  selector backend").

## Residual risk

- `hive-conductor-e2e-ui` must go green on the next CI evaluation; the
  evidence above says transient. If it reproduces on the same runner
  population across unrelated trees, it becomes a trunk repair in
  packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts (out of
  this PR's scope — this branch changes no frontend file).
- New advisories can land in any feed between this commit and CI's
  evaluation; the gate policy (upgrade when a fix exists) applies unchanged.
- The research-image venv proof here is a faithful reconstruction of the
  image's install contract (exact export command + trivy flags), not the
  built image itself; the go-binary HIGHs fixed in round 3 remain covered by
  that round's buildinfo evidence and stayed clean in the 03:29Z run.

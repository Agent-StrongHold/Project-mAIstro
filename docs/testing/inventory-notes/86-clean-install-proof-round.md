---
inventory-delta:
  tests/: +125
---

# #86 M3-A4 clean-install/deployment-profile proof — verification round

This round adds the #86 release proof itself: the harness
(`scripts/prove-installed-workspace.py`), its shipped input contract
(`docs/testing/installed-workspace-proof-manifest.schema.json`), its runbook
(`docs/testing/installed-workspace-proof.md`), and the contract suite that
drives the real script (`tests/release/test_installed_workspace_contract.py`).
`tests/: +80` is that suite in full — the original 54 collected cases plus
26 observation/drain regression cases added in the focused repair below. No
existing test was weakened, skipped, or deleted to make room for them.

## Current isolated-worker validation (starting HEAD `7b61c9c3e5`)

**Partial repair, not release proof or integration approval.** Earlier executed
claims below are historical; they were not assumed true. The assigned job
`971bce79b16348498ca9b05beccf1dbf` supplied no `check-*.log` files, and its
referenced prior result file was absent. The clean tree preserved two existing
lane commits. With no prior abort diagnostic available, this round selected
the smallest independently reproducible production defect rather than
rebuilding the lane again.

The unmodified harness falsely returned exit zero/all-family PASS when the
clean-target probe printed plain text, and when lifecycle stop reported
`drained: false, sandboxes_remaining: 0`. Required JSON observations were
previously enforced only by optional manifest expectations/payload fields.
The repair enforces JSON objects for clean-target, login, Workspace, effective
configuration, execution, lifecycle stop, persistence, post-restart request,
isolation controls/probes and fail-closed observations independently of those
optional fields. Stop must also report exactly `drained: true` and an integer
(not boolean/float) zero remaining sandboxes. Textual installer/start output
remains supported.

Tests drive the real CLI implementation with subprocess clients; all synthetic
observations are **harness contract tests**, not an installed product journey.
Before the production repair, the added tests produced **25 failures, 1 pass**;
after it, `uv run pytest tests/release/ -x -q` produced **263 passed** (80
harness tests plus 183 adjacent envelope/request-chain tests). The six lifecycle
cases cover missing/false/non-boolean drain and missing/boolean/float counts;
the 20 observation cases cover text and JSON arrays at ten mandatory steps.
The clean-probe cases also assert the installer was never launched.

Additional executed validation:

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed, 3487 files formatted.
- `uv run python scripts/check-suite-inventory.py --suite tests/` initially
  reported the expected **+26** drift; after recording it here, the check
  passed with **5954 collected node IDs**, no duplicate evidence. No baseline,
  grant or quality ledger changed.
- `uv run pytest tests/test_llm_gateway_compose.py
  tests/test_check_install_functions.py tests/test_check_deployment_claims.py
  tests/test_install_docker_sock.py
  packages/maistro-bootstrap/tests/test_sandbox_preflight.py
  packages/maistro-bootstrap/tests/test_delivery.py -x -q` — **84 passed**.
  These are adjacent rendering/preflight/stub tests, not clean-host evidence.
- `uv run python scripts/check-doc-links.py` — passed (2979 Markdown files,
  zero broken links).
- `uv run python scripts/check_assertion_quality.py` — passed (zero actionable
  findings; pre-existing invalid-escape SyntaxWarning).
- `uv run python scripts/check-reachability.py` — passed (1460 production
  modules, 153 unreachable).
- `uv run python scripts/check-install-functions.py` and
  `uv run python scripts/check-deployment-claims.py` — both passed.
- `git diff --check` — passed.

### Acceptance audit and remaining blockers

No live installation or provider calls were performed: this job supplies no
reviewed target/support manifest, existing target credential references or
authorized provider-call budget. Issue #86 explicitly does not authorize
creating these. All acceptance below remains **UNVERIFIED end-to-end**:

| Criterion | Evidence/limitation |
| --- | --- |
| Published/tag-pinned artifacts rather than developer checkout | Manifest/checkout rejection tests pass; no exact installed RC/digest evidence. |
| Healthy/authenticated supported services | Mandatory observation regression tests pass; no ordinary-user first run or login on an installed service. |
| Truthful optional/degraded services | Existing fail-closed harness tests pass; no installed required/optional service matrix. |
| macOS/non-default socket and supported Linux paths | No clean target on either OS was exercised in this round. Stub tests cannot close this host requirement. |
| External gateway effective Compose/runtime configuration | Existing effective-model mismatch tests pass; no installed external gateway or #87 same-request evidence. |
| Graceful stop/restart, lifespan cleanup, no orphan sandboxes | New regression tests reject absent/false drain and invalid counts; no installed lifecycle execution/persistent-state proof. |
| Sandbox/backend prerequisites | No clean-host sandbox capability probe or negative installed execution. ADR-093 floors are unchanged. |
| Tested commands become quickstart/install docs | Harness runbook exists; no live tested install commands can yet be promoted to quickstart. |

The ordinary-user journey (Workspace/Project access, real model and canonical
Goal/Graph/Run/NodeRun/Attempt IDs, restart persistence, two-user/two-Workspace
isolation and all installed failure cases), every advertised support row and
#87 same-artifact/configuration handoff are likewise UNVERIFIED.

Two additional concrete defects were reproduced and are **not repaired by
this focused commit**:

1. `write_bundle` serializes raw observed dictionaries. A synthetic
   `effective_config` command returning `password` and private-message marker
   fields persists both verbatim in `effective-config.json#/observed`.
   `install.log` redaction does not sanitize JSON payloads. Do not run this
   harness with real sensitive output before repairing bundle-wide privacy.
2. This harness's output is not the existing #1878 envelope format:
   `uv run python scripts/validate-installed-workspace-proof.py --bundle
   <synthetic-bundle> --profile <synthetic-profile> --mode structural` exits 1
   with `SCHEMA_INVALID` at `manifest.json#/files`, `manifest.json#/schema`
   and `results.json#/scenarios` (independent of the also-invalid minimal
   synthetic profile). Passing the local `--verify` is not interoperability
   evidence. An adapter/convergence repair and independent reviewed profile
   are still required before claiming composition.

Detailed baseline, red-test, release-suite, residual-reproduction and gate logs
are retained in the assigned job directory. These findings prevent a
MERGE-READY verdict; do not interpret the historical claims below as closure.

## Filename reconciliation with #1878

The issue proposes the deliverable name
`docs/testing/installed-workspace-proof.schema.json`, but develop already
ships that exact path as the #1878 installed-workspace proof **envelope**
schema (the reviewed-profile/manifest/results evidence bundle validated by
`scripts/validate-installed-workspace-proof.py`). The two documents are
different contracts: #1878's schema governs the evidence bundle an installed
proof produces; this lane's schema governs the reviewed **manifest input**
that drives `scripts/prove-installed-workspace.py`. Overwriting the #1878
file would break its validator, its 96-case suite, and the `quality.yml`
fail-closed gate step, so the manifest contract ships under the adjacent name
`installed-workspace-proof-manifest.schema.json` and every reference (harness
`SCHEMA_PATH`, contract test, runbook link, Gate C file check) points there.
The envelope validator is the intended fail-closed checker for installed
proof evidence. Filename reconciliation alone does not make these formats
compose: the current validation addendum above records a reproduced schema
mismatch that still requires repair.

## Repair addendum: develop re-apply restored (this round)

The lane's earlier history was rebuilt onto the assigned develop base
(`4de7e906d`) as a single squash, and that rebuild accidentally reverted
develop-side changes in ~440 files the lane never touched (stale `get.sh`
upgrade functions from #353, `quality.yml`/`ci.yml` motion, `uv.lock`, the
#1878 envelope schema, resurrected `041/043/045` duplicate-head migrations,
and the RETIRED `stream1-diagnostic.yml`). This round restores every such
file to its develop content and prunes the resurrected files, so the branch
diff vs develop is exactly the seven deliverable paths above (with the
manifest schema at its reconciled name). Re-derived after the restore:
`alembic heads` is single-headed (`068`), `tests/release` is 237 passed (the
lane's 54 plus develop's #1878/#1879 suites undamaged), full suite inventory
matches across all 21 suites, `check-workflow-inventory`/`check-reachability`
+provenance/`check-ratchet-provenance`/`check-install-functions`
/`check-required-checks`/`check-branch-protection`/`check-doc-links` all exit
0, and `ruff check`/`ruff format --check` are clean.

The harness is a release *orchestrator*: it launches the public
installer/lifecycle/product-client commands a reviewed manifest names, collects
the evidence, and asserts the contract. It does not re-implement admission,
authentication, Binding bootstrap, or the executor, and it never creates a
credential, a grant, or a provider call it was not authorized to make.

## What the new suite protects

The tests drive the shipped script — through its own module and its own CLI —
rather than re-describing it, because a harness exercised only by prose is
exactly the "structural validity is never run occurrence" failure the issue
warns about.

* **Manifest contract** (cases 1–13): the shipped schema is the enforced
  contract — a missing section, an unexpected key, a keyword the schema subset
  does not implement, and a moving branch artifact are all refused; a
  headless row needs an independently reviewed profile; a `ui` row must use the
  browser login; the four mandatory fail-closed cases are required by name;
  isolation needs two distinct users and two distinct workspaces.
* **The checkout is not the artifact** (case 44): a manifest whose command
  names a path inside the harness's own checkout is refused before anything
  runs, in-process and through the CLI (exit `2`). The published,
  digest-pinned release is the artifact under test.
* **Secret hygiene** (cases 14, 41, 43): a secret-shaped literal is refused
  anywhere in a manifest, and a manifest naming one never reaches the bundle;
  the installer log redacts secret-shaped output.
* **Stop-before policy** (cases 15, 16): a command that would elevate, change
  a socket/group permission, generate or import a credential, create a grant,
  or set up a paid provider account blocks its family and is **not executed**.
* **Clean-target contract** (case 17): an unmet requirement blocks the
  install instead of proceeding.
* **Absence is not permission** (cases 18–20): an absent credential or an
  unauthorized budget makes the provider-touching families `NOT_RUN`; the
  authorized ceiling is a bound, and reaching it blocks the proof.
* **Truthfulness of the evidence** (cases 21–34): a missing canonical id, an
  effective gateway/model that differs from the declared one, a missing
  response digest, an unreported provider-call count, a broken restart
  correlation, a stop that leaves sandboxes behind, a leaky or undelied
  isolation probe, a failed isolation positive control, a fail-closed case that
  reports success or blocks without a recovery pointer, and an effective
  configuration that disagrees with the declared provider are all `FAIL`.
* **Bundle integrity** (cases 35–38, 44–48): a complete run passes every
  family and writes the whole bundle; the bundle hashes its payloads and
  `--verify` detects a tampered file; a manifest-listed evidence reference that
  names `results.json` itself is refused; the CLI exits `2` on an invalid
  manifest, `1` when a family does not pass, and `0` only on a complete,
  verified, all-PASS run; a non-empty output directory is never overwritten;
  the manifest is validated before anything is executed.
* **Applicability and provenance** (cases 39, 40, 42, 49): `NOT_APPLICABLE`
  is refused outside the `BROWSER_LOGIN` subcheck; a headless row records
  browser login as inapplicable; the target never inherits the controller's
  environment; and the reference manifest is reproducible from the shipped
  builder.

Two extra cases (26, 27) assert the recording the issue requires: the
ordinary application principal ids and the canonical `run_id` / `node_run_id` /
`attempt_id` land in `results.json`, together with the support row (id, browser
mode, OS, architecture, runtime, context, store profile) and the controller's
own digest and commit.

## Executed evidence (this round, this worktree)

- `uv run pytest tests/release/ -q` — **54 passed** (14.4s). The suite is the
  proof of the harness contract.
- `uv run python scripts/prove-installed-workspace.py --manifest <reviewed-style
  manifest> --output <dir>` — exit `0`, all five families `PASS`, full bundle
  written; `--verify <dir>` — exit `0`, "structurally valid";
  `observed_provider_calls=2`, `max_model_calls=5`, `remaining_model_calls=3`,
  `all_families_pass=true`, `bundle_verified=true`.
- `python3 scripts/check-doc-links.py` — "markdown files scanned: 1393 /
  broken relative links: 0 / Every relative markdown link resolves."
- `uv run ruff check .` — "All checks passed!"; `uv run ruff format --check .`
  — "2641 files already formatted".
- `python3 scripts/check-reachability.py` — before the Gate C edit: "1144
  production modules, 189 unreachable … NEWLY UNREACHABLE:
  scripts/prove-installed-workspace.py (@tool/prove-installed-workspace)"; after:
  "1144 production modules, 188 unreachable", exit `0`. The Gate C step is
  what roots the tool.
- `python3 scripts/check-suite-inventory.py --suite tests/` — "ok tests/: 4250"
  (exit `0`) after the sanctioned `--update --note 86-clean-install-proof-round`.
- `python3 scripts/check-suite-inventory.py --suite tests/ --update --note
  86-clean-install-proof-round` — "DRIFT tests/: expected 4249, collected 4250";
  the delta was written by the tool, not by hand.
- `uv run python scripts/check_assertion_quality.py` — "assertion-quality
  actionable findings: 0".
- Broad gate batch, each exit `0`: `check-workflow-write-safety`,
  `check-required-checks`, `check-uv-setup`, `check-retired-guidance`,
  `check-contract-markers`, `check-shipped-surface-truth`,
  `check-release-consistency`, `check-backlog-consistency`,
  `check-security-inventory`, `check-credential-authority`, `check-wiring-reads`,
  `check-agent-store-writes`, `check-convergence-matrix`,
  `check-reachability-dispositions`, `check-execution-lifecycles`,
  `check-model-egress`, `check-public-routes`, `check-promotion-surface`,
  `check-image-inventory`, `check-durable-table-inventory`,
  `check-connection-credentials`, `check-owned-store-access`,
  `check-secret-field-labels`, `check-cross-package-imports`,
  `check-frontend-api-routes`, `check-merge-markers`,
  `check-install-functions`, `check-deployment-claims`, `check-compose-secrets`.
- Related suites re-run at this head: `tests/test_llm_gateway_compose.py
  tests/test_check_install_functions.py tests/test_check_deployment_claims.py` —
  43 passed; `tests/test_install_docker_sock.py
  tests/test_install_engine_floor.py tests/test_install_arm64_check.py
  tests/test_installer_repository.py tests/test_install_credential_helper.py
  tests/test_install_mnemonic_handling.py` — 77 passed;
  `packages/maistro-bootstrap/tests/test_sandbox_preflight.py
  packages/maistro-bootstrap/tests/test_delivery.py` — 19 passed.

### Gates that could not run here (and why)

- `python3 scripts/check-vulture-baseline.py` — exit 1, `No module named
  vulture`. The ratchet workflow scans `packages/*/src` only, so `scripts/` is
  out of its scope; the finding is a missing local dependency, not a new dead
  module.
- `python3 scripts/check-radon-baseline.py` — exit 1, `No module named radon`.
  The default scan path is `packages/maistro-core/src`; this round touches no
  `packages/` source.

## Prior-round evidence (recorded at head `c5e070d9`, branch `auto-86`)

The claims below were executed in the **previous** round of this issue and are
kept for provenance; they were not re-derived in this round except where
re-listed above.

- `scripts/check-install-functions.py` — exit 0 (every installer command
  resolves to a defined function, builtin, or justified external; #807).
- `scripts/check-deployment-claims.py` — "OK: every component and shipping
  backend named in DEPLOYMENT-STANCE.md exists" (truthful component claims).
- `scripts/check-compose-secrets.py` — "ok: 8 tracked Compose file(s) hand out
  no credential" (#367).
- `pytest tests/test_llm_gateway_compose.py` — 9 passed; renders the Compose
  files the way Compose does and asserts `LITELLM_BASE_URL` is the one gateway
  input every service agrees on (#808; criterion "external supported gateway
  configuration is proven through rendered Compose/runtime configuration").
- `pytest tests/test_install_docker_sock.py` — 7 passed; the Colima-style
  non-default Docker-socket branch executes end to end against a stub `docker`
  and records `MAISTRO_DOCKER_SOCK`; default socket records nothing (#807;
  criterion "macOS/non-default Docker socket ... exercised rather than
  inferred from one runner OS" — satisfied the way the repo sanctioned in the
  807 notes: branch exercise instead of a macOS CI leg).
- `pytest packages/maistro-bootstrap/tests/test_sandbox_preflight.py
  packages/maistro-bootstrap/tests/test_delivery.py` — 19 passed (preflight
  banner reports what can/cannot isolate; `PINNED_IMAGES` delivery map;
  #81/#348/#349).
- Live SIGTERM drain (manual spawn of `maistro_server.main` under uvicorn,
  in-memory spine): on SIGTERM the process logs `task_runner_stopped` →
  `all_sandboxes_cleaned_up count=0` → `maistro_engine_stopped` → "Application
  shutdown complete" and exits — lifespan cleanup runs and no sandbox is
  orphaned (#819; criterion "graceful stop/restart executes lifespan cleanup").

## Environmental caveats found while validating (not product defects)

- `/tmp` is a tmpfs whose inodes were 100% exhausted by prior jobs' scratch;
  this failed one `test_install_docker_sock` case with
  `OSError: [Errno 28] No space left on device` on a symlink. After clearing
  only pytest's own `/tmp/pytest-of-dev` scratch, the file passes 7/7.
- A cold boot of `maistro_server.main` takes ~161s on this workstation's I/O,
  exceeding the 60s readiness budget inside `test_sigterm_shutdown.py`; the
  same server boots, serves, and drains cleanly when given the time (live
  evidence above). CI hardware is unaffected.

## Coverage-gate repair round (CI run 45847296829, job 140018816174)

The merge-queue evaluation at head `85d4c66bc945` failed exactly one job:
`Coverage gate (publish-set floor + diff coverage)`. Its diff-coverage step
scored `scripts/prove-installed-workspace.py` at **83.7% of 1045 changed
lines (floor 90%)**; the `Event loop is closed` lines in the same log are
`PytestUnhandledThreadExceptionWarning`s from `test_tasks_run_identity.py`,
emitted as annotations inside a step whose own pytest run passed (6402
passed/140 skipped) — they are not the failure. `tests/: +45` above is this
round's increment (80 -> 125): the same file, so no new suite.

The repair adds the missing evidence rather than touching the gate: 45 cases
in `tests/release/test_installed_workspace_contract.py` driving the harness's
own module and CLI — the shipped schema subset's rejection paths
(`validate_manifest` on every unsupported shape, `load_contract` on
unreadable/malformed/non-object schema files), the cross-field rules not yet
reached (headless login.mode, duplicate workspaces), stop-before gating on the
RESTART/ISOLATE/FAIL_CLOSED families, install effective-config model and
model_tier mismatches, restart correlation scope mismatches, restart
provider-call-count reporting, the canonical login subcheck name, install-log
truncation, step timeout/missing-binary recording, `check_expect_json`
expectation shapes, `verify_bundle`'s structural rejections (index shape, file
map, results trust, scenario/subcheck shapes, evidence references, junit
cases), and the CLI `--validate-manifest`/`--verify`/argument-contract
surfaces including the closeout behaviour when bundle self-verification fails.
One genuinely dead helper found by the measurement — `_check_type`, zero
callers — was removed from the harness instead of being pinned by a test.
The suite's fixture builder and every prior assertion are unchanged.

Executed validation of this round (starting head `85d4c66bc945`):

- `uv run pytest tests/release/test_installed_workspace_contract.py -q` —
  **125 passed** (was 80).
- Local reproduction of the failing gate with CI's own tooling:
  `uv run coverage run --branch --source=scripts -m pytest
  tests/release/test_installed_workspace_contract.py -q` then
  `uv run coverage xml` then `uv run python scripts/check-diff-coverage.py
  coverage.xml --base 7ba29c1cd0e45` reproduced **83.7% / 1045 changed lines,
  FAIL** before the repair and **`ok: every measured file this change touches
  is at or above 90% lines / 80% branch arcs`** after it — measured at
  **98.7% lines (1026/1040) and 95.6% branch arcs (461/482)**. The local
  measurement is a strict subset of CI's root-suite producer (nothing outside
  `tests/release/` imports the harness), so CI's number can only be higher.
- `uv run python scripts/check-suite-inventory.py --suite tests/` — reported
  the expected +45 drift before this note recorded it; passes after (6565
  collected node IDs).
- `uv run ruff check .` and `uv run ruff format --check .` — passed.

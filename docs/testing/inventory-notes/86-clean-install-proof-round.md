---
inventory-delta:
  tests/: +54
---

# #86 M3-A4 clean-install/deployment-profile proof — verification round

This round adds the #86 release proof itself: the harness
(`scripts/prove-installed-workspace.py`), its shipped contract
(`docs/testing/installed-workspace-proof.schema.json`), its runbook
(`docs/testing/installed-workspace-proof.md`), and the contract suite that
drives the real script (`tests/release/test_installed_workspace_contract.py`).
`tests/: +54` is that suite in full — 50 test functions, 54 collected cases
(`test_a_stop_before_command_blocks_its_family_without_executing` is
parametrized over the five stop-before categories). No existing test was
weakened, skipped, or deleted to make room for them.

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

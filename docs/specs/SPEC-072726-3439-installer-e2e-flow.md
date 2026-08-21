---
id: SPEC-072726-3439
title: "End-to-end installer: curl/iex link to first model call and tutorial"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-27
substrate:
  - maistro-engine#SPEC-180
implements: []
related:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-033
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests:
  - packages/maistro-bootstrap/tests/test_plan.py
  - packages/hive-conductor/backend/tests/test_api.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-072726-3439: End-to-end installer: curl/iex link to first model call and tutorial

## Context

The target user journey is: grab a `curl` link (macOS/Linux/WSL2) or `iex` link
(native Windows) → an installer walks through the settings questions (optional
features, initial admin name and password, initial daily-driver user 1 name and
password, entropy generation when cryptographic hierarchical identity is
enabled) → the installer generates the install files (compose bundle for image
pull, compose + Makefile for source build) → brings the stack up → launches the
UI → setup finishes in the UI → the first model call succeeds → the tutorial
starts.

Most of the skeleton already exists on `develop`:

- `get.sh` (curl entrypoint) and `get.ps1` (iex entrypoint; WSL2 enablement with
  RunOnce reboot-resume) both funnel into `install.sh`.
- `install.sh` runs the `maistro-install` questionary wizard
  (`run_feature_wizard`, install.sh:746), materializes a reviewable plan to
  `.maistro-install/`, generates `.env` secrets, runs
  `docker compose up -d --build`, waits on health endpoints, installs the
  `maistro` CLI, and opens the browser.
- Hive Conductor has a real first-run flow: `AuthGuard` polls
  `GET /v1/setup/status`; `Setup.tsx` collects admin + daily-driver credentials
  and POSTs the public one-shot `POST /v1/setup/complete`
  (backend/routes/setup.py:50), which Argon2-hashes both passwords, optionally
  generates a `ConductorSeed` (BIP39, ADR-021) and shows the 24-word mnemonic
  exactly once, then auto-logs-in.

What breaks the journey today (verified against the tree at develop@84eff22):

1. **`/v1/install/*` is dead.** `backend/routes/install.py` imports
   `maistro_bootstrap.session.get_session_defaults`, which does not exist, so
   both endpoints always 503; `frontend/src/pages/Install.tsx` is not routed
   in `App.tsx`; and the `/v1/install` prefix is auth-gated, which is
   chicken-and-egg for pre-setup use. (`POST /v1/install/plan` is deliberately
   retired — regression-pinned in `test_api.py` — so the session endpoint is
   the only wizard contract to revive.)
2. **No path from UI to a working model call.** Provider API keys live only in
   `.env` consumed by the LiteLLM container; changing them requires hand-editing
   `.env` and recreating the container. `pages/Credentials.tsx` +
   `maistro.credentials` only catalog PM integrations (Jira, GitHub, …) — no
   OpenAI/Anthropic/Gemini entries. Nothing in the UI can get from "stack is up"
   to "a completion succeeded".
3. **`delivery_mode` is metadata.** `image_pull` vs `source_build` changes
   nothing: compose always builds from source; no pinned images are published;
   no Makefile exists.
4. **First-run UX bugs.** `Onboarding.tsx` renders above `AuthGuard`
   (App.tsx:182), so the modal covers the Setup wizard on a fresh install.
   `SetupChecklist` (server-backed, auto-completing) is mounted only on
   `Fleet.tsx`, invisible to a default install. The materialized
   `tutorial-todo.md` is read by nothing.
5. **Identity/vault gaps.** The `identity` extra may be absent from the
   hive-conductor image and `setup.py:85-92` swallows the ImportError silently
   (mnemonic silently `None`). Nothing initializes the age vault
   (`secrets.age` / `admin.key`), so vault-first secret resolution
   (services/secrets.py) always falls through to env.
6. **Latent breakage.** The materialized reactor compose override declares a
   `maistro-reactor` service with neither `image:` nor `build:` and no matching
   base service. Default chat model differs across `config.py:35`,
   `setup.py:121`, and `docker-compose.yml:144`; only the compose value exists
   in `litellm_config.yaml`.

## Goals

- One command from a bare machine (curl on macOS/Linux/WSL2, iex on Windows) to
  a running Hive Conductor with setup finished, a successful first model call,
  and the tutorial started.
- Terminal wizard collects: optional features, admin name + password,
  daily-driver user 1 name + password, and (for
  `crypto_profile: distributed_identity_root`) generates seed entropy — with
  passwords and mnemonics never written to answers YAML or any materialized
  artifact.
- `delivery_mode` becomes real: `image_pull` uses pinned published images;
  `source_build` generates a compose bundle + Makefile and builds locally; both
  produce identical runtime behavior.
- The UI owns the tail of the journey: provider key entry, first-model-call
  verification, and a checklist-driven tutorial — no hand-edited `.env`.

## Non-goals

- Stronghold / multi-tenant installs (Copier hints only, per SPEC-180).
- `unsafe_host` sandbox profile or any host-privileged install path.
- `full_all_crypto` wallet/spending surface (stays policy-gated downstream).
- Production DNS for the curl/iex short links (constant swap when ready).
- SSO; only local bootstrap accounts are in scope.

## Decision

The flow is split into five phases. Each phase lands independently on
`develop` and is useful on its own; the acceptance test only passes when all
five are in.

### Phase 0 — repair the base

- Add `maistro_bootstrap/session.py` exposing
  `get_session_defaults(partial: dict | None) -> dict` as a thin wrapper over
  `schema.merge_session_payload`, and make `/v1/install/*` public **only while
  setup is incomplete** (same one-shot boundary as `/v1/setup/complete`),
  normal auth afterwards. `POST /v1/install/plan` stays retired — the session
  shape is the single wizard contract (regression-pinned by
  `test_install_plan_endpoint_retired`).
- Delete the unrouted `frontend/src/pages/Install.tsx` (the terminal wizard and
  `Setup.tsx` are the real surfaces; the JSON-textarea page misleads).
- Fix the reactor compose override: emit `build:` (context `.`, existing
  Dockerfile target) alongside `profiles: ["reactor"]`, or omit the service
  until a reactor image exists — override must pass `docker compose config`.
- Single source of truth for the default chat model: one constant, referenced
  by `config.py`, `setup.py`, and compose env; must exist in
  `litellm_config.yaml`.
- Render `Onboarding` inside the authenticated shell (below `AuthGuard`), and
  mount `SetupChecklist` on the main dashboard.
- Make identity failures loud and atomic: when `crypto_identity` is requested
  but `maistro.identity` cannot import or generate, `setup.py` fails the
  request (503 with an actionable detail) **before creating any account** —
  completing setup without the mnemonic would lock the one-shot endpoint
  behind its 409 guard with no later provisioning step. The operator retries
  after repairing the dependency, or deselects the module. Installing the
  `identity` extra in the hive-conductor image is blocked for now: the
  Chainguard base is Python 3.14 and `coincurve` (via `bip-utils`) publishes
  no cp314 wheels (21.0.0 caps at cp313) while its source build is broken
  against current cffi — restoring in-image identity moves to Phase 3 (pin a
  3.13 wheel-building stage, or pick up coincurve's cp314 wheels when
  released).

### Phase 1 — wizard collects credentials and entropy

- Extend `wizard.py`: after the existing feature/profile questions, prompt for
  admin username + password and daily-driver username + password using
  questionary password prompts (confirmation prompt each). Schema stays
  secret-free: `InstallAnswersV1` continues to carry names only.
- Credentials are written to `.maistro-install/bootstrap-credentials.json`,
  mode 0600, gitignored, containing usernames, passwords, requested
  `optional_modules` (derived from `crypto_profile` and feature picks), and
  `hardware_preset`. The file is **consumed exactly once** and shredded
  (overwrite + unlink) by the installer after successful bootstrap.
- Entropy: no separate entropy step is needed at wizard time —
  `ConductorSeed.generate()` (ADR-021) draws from the OS CSPRNG server-side at
  setup. The wizard's `crypto_profile` answer decides whether it runs.
  `no_crypto` skips it entirely.
- Non-interactive installs (`--answers-file` without a TTY) skip credential
  prompts; the UI Setup wizard remains the fallback. For headless installs
  that still want terminal-driven bootstrap (CI smoke tests included), a
  pre-staged credentials file may be supplied via
  `MAISTRO_BOOTSTRAP_CREDENTIALS_FILE` — same 0600 requirement, same
  consume-once-and-shred semantics as the wizard-written file.

### Phase 2 — generated install files

- `materialize_install_artifacts` grows two delivery renderers:
  - `image_pull`: writes a **standalone** `compose.install.yml` (a complete
    compose file, not an override) whose services carry only pinned `image:`
    references (`ghcr.io/agent-stronghold/…@sha256:…`, digests injected at
    release time) and no `build:` keys at all. An override merged onto the
    root compose cannot express this — Compose merges mappings, so the base
    `build:` keys would survive and `up --build` would still build source.
  - `source_build`: writes a `Makefile` (recording the pinned source
    revision in its header) with targets `install`, `up`, `down`, `logs`,
    `status`, `backup`, `teardown`, `update` wrapping the exact compose
    invocations `install.sh` uses against the root compose file — the
    operator-facing escape hatch. All compose invocations pass
    `--project-directory` at the repo root so `.env` interpolation and
    relative bind mounts resolve identically in both modes.
- `install.sh` consumes the delivery manifest: in `image_pull` mode it runs
  compose against the standalone file only and **never passes `--build`**
  (`docker compose up -d`, pull policy from the pinned digests); in
  `source_build` mode it keeps today's `up -d --build` against the root
  compose file. Until images are published (Phase 5), `image_pull` falls back
  to `source_build` with a loud warning rather than failing.

### Phase 3 — bring-up performs the bootstrap

- After `start_engine` health checks pass, a new `bootstrap_first_run` step in
  `install.sh` POSTs `bootstrap-credentials.json` to `POST /v1/setup/complete`.
  On success it: prints the returned mnemonic (if any) in a framed panel,
  requires an interactive "I have written this down" confirmation, never writes
  it to disk, then shreds the credentials file. A 409 (already set up) is
  **terminal consumption, not retry state**: the credentials file is shredded
  there too — otherwise a success response lost between server commit and
  client shred would leave both plaintext passwords on disk indefinitely.
  Retry semantics (file kept) apply only to failures that occur before setup
  commits (connection errors, 4xx/5xx other than 409).
- Setup (server-side, same request) initializes the age vault: generate
  `admin.key` + empty `secrets.age` under `CONDUCTOR_DATA_DIR` if absent, so
  vault-first secret resolution is live from day one. This requires the `age`
  runtime in the conductor image — the thin Chainguard runtime ships no `age`
  binary and `maistro/vault.py` shells out to it for every read and write.
  Either copy a static `age`/`age-keygen` into the runtime stage or adopt an
  in-process implementation (e.g. `pyrage`) behind the existing Vault API;
  the installer smoke test must exercise a vault round-trip.
- The identity root must survive the request: `distributed_identity_root`
  setup persists the seed **encrypted at rest** (in the age vault, under the
  same `CONDUCTOR_DATA_DIR` trust boundary) before `seed.zero()` runs — the
  mnemonic shown once to the operator is the *recovery* path, not the only
  copy. Without this, ADR-021 signing (AgentSpec, audit, approvals) has no
  private root after the response is sent or the process restarts, unless the
  operator re-enters the mnemonic. Recovery: a documented re-import flow that
  accepts the mnemonic and re-materializes the encrypted seed.
- `install.sh` records recovery/rollback commands (`status`, `logs`, `restart`,
  `backup`, `teardown`) into `.maistro-install/RECOVERY.md` and prints them in
  `print_success`.
- The browser then opens (existing `open_browser`) to a UI that shows Login —
  not Setup — because setup completed from the terminal. First admin login
  lands on the dashboard with the SetupChecklist showing the remaining items.

### Phase 4 — finish in the UI: provider keys, first call, tutorial

- LLM provider keys are deployment-wide vault material, not per-user
  integration credentials — so they get a dedicated API surface rather than
  riding the existing credentials routes: `PUT /v1/providers/{name}/key`
  writes **directly to the age vault** and `POST /v1/providers/{name}/activate`
  reads from it. The existing `UserCredentialStore` (per-user Fernet file
  behind `routes/credentials.py`) is not used for LLM keys — routing them
  there would satisfy neither the vault contract nor single-copy storage.
  `pages/Credentials.tsx` hosts the UX (an "LLM providers" section) but calls
  the providers API for this kind.
- Provider endpoints are privileged: they use the LiteLLM master key, mutate
  the global model registry, and can trigger billed calls. Both routes go into
  `_PROTECTED_OPS` under `config.write` (admin or elevated), with a negative
  authorization test proving a plain daily-driver session is refused.
- `POST /v1/providers/{name}/activate` registers/updates the model set with
  the running LiteLLM instance via its admin API (master key auth, dynamic
  model add) — no container recreate — then issues a one-token test completion
  and returns its result; that success is the journey's "first model call".
- `setup_checklist.py` items become the tutorial spine, seeded from the plan's
  tutorial todos at bootstrap time (replacing the orphaned `tutorial-todo.md`),
  and are **split by account**: admin items (confirm recovery phrase, add +
  activate a provider key) and daily-driver items (send first chat, create
  first DAG via the guided smoke prompt) — the admin role is blocked from
  `/v1/chat/` by design, so the checklist explicitly directs the account
  switch before any chat-dependent step. `Onboarding.tsx` becomes a thin
  intro that hands off to the checklist instead of a parallel system.

### Phase 5 — release plumbing

- CI workflow `release-installer.yml` (tags + manual dispatch, not a per-PR
  gate): build + push pinned images to GHCR (digests surfaced for the
  `PINNED_IMAGES` map), publish a `SHA256SUMS` manifest for
  `get.sh`/`get.ps1`/`install.sh`, and run the installer smoke test with
  `--answers-file` + staged disposable credentials — no secrets required.
  The initial smoke leg is Ubuntu + Docker; macOS (Colima), WSL2, and Podman
  legs are follow-ups (hosted runners make them slow/awkward, not impossible).
- `get.sh`/`get.ps1` verify the fetched `install.sh` against a published
  checksum before executing. Swap `DEFAULT_CURL_INSTALL_URL` to the production
  domain when DNS lands (single-constant change, unchanged behavior).

## Acceptance criteria

- **AC-1 (bare machine, curl):** on a clean Ubuntu VM with Docker absent,
  `curl -fsSL <link> | bash` + wizard answers ends with: stack healthy, admin +
  daily-driver accounts created, mnemonic shown once in terminal,
  `bootstrap-credentials.json` gone, browser opened to Login.
- **AC-2 (iex):** on Windows 11 without WSL, `irm <link> | iex` reaches the
  same end state (allowing one reboot-resume).
- **AC-3 (first model call):** from the freshly installed UI, adding a provider
  key via Credentials and pressing Activate yields a successful test
  completion, with the key stored in the vault and never written to `.env`.
- **AC-4 (tutorial):** after AC-3, the dashboard SetupChecklist shows the
  provider item auto-completed and walks the remaining tutorial items; the
  guided smoke prompt creates and completes a minimal DAG.
- **AC-5 (delivery parity):** `image_pull` and `source_build` installs produce
  identical `docker compose config` output modulo `image:`/`build:` stanzas.
- **AC-6 (no secret leakage):** grep of answers YAML, materialized artifacts,
  and shell history hooks confirms no passwords, API keys, or mnemonics at
  rest; `pytest packages/maistro-bootstrap/tests` asserts the schema rejects
  password fields.
- **AC-7 (idempotence):** re-running the installer over a healthy install
  performs updates only — no 409 failures, no credential re-prompt, no data
  loss.

## Testing

- Unit: schema round-trips (no secret fields accepted), session-defaults merge,
  plan/materialize renderers for both delivery modes (`test_plan.py`), Makefile
  render snapshot.
- API: `/v1/install/*` pre/post-setup auth posture, `/v1/setup/complete`
  bootstrap-file path incl. 409 idempotence and `identity_unavailable`
  surfacing, provider activate happy-path + bad-key path (LiteLLM stubbed).
- Frontend: AuthGuard/Onboarding ordering (fresh install shows Setup or Login,
  never the modal first), SetupChecklist on dashboard, Credentials
  llm_provider flow.
- Installer smoke (CI, Phase 5): full `get.sh` run in container matrix with
  `--answers-file` plus disposable bootstrap credentials pre-staged via
  `MAISTRO_BOOTSTRAP_CREDENTIALS_FILE` (a noninteractive run without that
  file skips credential collection and cannot assert account creation),
  asserting AC-1's end state minus the browser — including a vault
  round-trip and that the staged credentials file was shredded.

## Open questions

- Should the terminal print the mnemonic at all, or defer reveal to first UI
  login (terminal scrollback vs. an extra server-held-seed window)? Current
  decision: print + confirm in terminal, matching "generates entropy" during
  install; revisit if threat model tightens.
- LiteLLM dynamic model registration API surface pinning — `main-latest` is
  unpinned today; Phase 5 should pin the LiteLLM image digest too.
- Podman parity for the docker.sock-dependent builder mounts on `image_pull`.

## References

- docs/install/default-installer.md — prior rollout checklist this spec
  supersedes in practice
- docs/specs/SPEC-180-maistro-install-bootstrap.md — answers schema / plan
  contract this builds on
- docs/adr/ADR-021 — BIP39/BIP32 HD identity root (`ConductorSeed`)
- packages/maistro-bootstrap/ — wizard, schema, plan, materialize
- packages/hive-conductor/backend/routes/setup.py — one-shot bootstrap endpoint

# Install resolver matrix

This document maps **feature selections** (checkboxes in the TUI or keys in an answers file) to **concrete commands**: `uv` extras, Docker Compose profiles, and Copier templates per [ADR-033](../adr/ADR-033-templates-and-copier-workflow.md).

For automation, use [`maistro-install`](../../packages/maistro-bootstrap/README.md) from the repo root after `uv sync --extra bootstrap`, or pass `--answers-file install-answers.yaml`.

---

## Import shadowing (pytest / dev)

Run from repo root with the same `PYTHONPATH` order as [`pyproject.toml`](../../pyproject.toml) `[tool.pytest.ini_options]` `pythonpath`:

```bash
PYTHONPATH="packages/maistro-core/src:packages/maistro-server/src:packages/maistro-turing/src:packages/maistro-canvas/src:." \
  uv run python -c "import maistro; print(maistro.__file__)"
```

**Observed output (2026-05-13):**

```text
.../maistro-engine/packages/maistro-core/src/maistro/__init__.py
```

The **first** path entry wins for the top-level `maistro` package. Agent spec, recipes, and spawner live under `packages/maistro-core/src/maistro/agents/`. Root `tests/` should import the FastAPI app from `maistro_server.main`, not a duplicate `maistro.main`.

---

## Feature matrix

| Checkbox id | User-facing label | `uv` / workspace | Compose profiles (optional) | Copier / external |
|-------------|-------------------|------------------|------------------------------|-------------------|
| `core_lib` | Core library (agents, memory, classifier, …) | Default dev: `uv sync` then work in `packages/maistro-core`. Optional: `uv sync --package maistro-core --extra llm --extra sandbox --extra observability` when developing features that need LLM/sandbox/observability. | None (library-only). | N/A |
| `tui` | TUI / CLI helpers (Typer + Rich) | `uv sync --package maistro-core --extra tui` (see [maistro-core pyproject](../../packages/maistro-core/pyproject.toml)). | None. | N/A |
| `server` | HTTP API (FastAPI) | Use `packages/maistro-server`: `uv pip install -e ./packages/maistro-server` or run tests from repo with full `uv sync`. | Default stack includes `maistro-engine` service in [docker-compose.yml](../../docker-compose.yml). For slice examples see [compose-slices.example.yml](./compose-slices.example.yml). | N/A |
| `canvas` | Canvas Studio package | `uv pip install -e ./packages/maistro-canvas` plus root optional `uv sync --extra browser` for Playwright when needed. | None in default compose; add your own profile if you containerize canvas. | N/A |
| `turing` | Autonoetic extensions | `uv pip install -e ./packages/maistro-turing`. | None in default compose. | Scaffold an autonoetic product via `templates/autonoetic/` (Copier). |
| `webui` | Open WebUI chat shell | Not a Python extra; use Compose. | See [compose-slices.example.yml](./compose-slices.example.yml) for **naming patterns** (default [docker-compose.yml](../../docker-compose.yml) keeps WebUI always-on). | N/A |
| `data` | Postgres only | N/A | Use profile naming from [compose-slices.example.yml](./compose-slices.example.yml) in a local override. | N/A |
| `llm_proxy` | LiteLLM sidecar | N/A | Same. | N/A |
| `observability` | Langfuse | N/A | Same. | N/A |
| `hive_conductor` | Hive Conductor package (API + UI; base compose under `packages/hive-conductor/`) | `uv pip install -r packages/hive-conductor/backend/requirements.txt` (see package README). | Base file: `packages/hive-conductor/docker-compose.yml`. Optional fragments under `packages/hive-conductor/compose/fragments/`. | N/A |
| `product_conductor` | Single-tenant multi-user (Conductor-shaped) | Align with downstream repo; engine stays library-only. | Usually product repo’s compose. | Copier: [`templates/single-tenant-multi-user/`](../../templates/single-tenant-multi-user/). |
| `product_stronghold` | Multi-tenant enterprise | **Not vendored** in this repo — the external Stronghold target is a prerequisite. | Stronghold’s own charts/compose. | Incomplete README seed only: [`templates/multi-tenant/`](../../templates/multi-tenant/); no round-trip claim. |
| `product_turing` | Autonoetic product | Downstream product repo. | Product compose. | Copier: [`templates/autonoetic/`](../../templates/autonoetic/). |

---

## Compose add-ons (`compose_addons`)

Second multiselect in interactive `maistro-install`, or `compose_addons` in the answers file. These are **optional compose merges** (for example Hive + Phoenix). The CLI prints:

1. Feature commands (`features`)
2. **Validate** lines (`docker compose … config`) for selected add-ons
3. **Podman install** preface (only when an add-on defines `podman compose` run lines)
4. **Run** lines (`podman compose … up`) for those add-ons

| Add-on id | Label / intent |
|-----------|----------------|
| `hive_phoenix` | Merge [`packages/hive-conductor/compose/fragments/phoenix.yml`](../../packages/hive-conductor/compose/fragments/phoenix.yml) with the Hive base compose (`--profile observe`). |

---

## Answers file schema (YAML)

Used by `maistro-install --answers-file`:

```yaml
features:
  - core_lib
  - server
  - webui
compose_addons:
  - hive_phoenix
product: single-tenant-multi-user  # optional: autonoetic | multi-tenant | none
dry_run: true
```

- `features`: list of checkbox ids from the table.
- `compose_addons`: optional list of add-on ids (see **Compose add-ons** above).
- `product`: for `single-tenant-multi-user` and `autonoetic`, the CLI prints a root-dispatcher
  command such as `uv run copier copy --data product_template=autonoetic . ../my-product`.
  The repository-root `copier.yml` selects the matching payload under `templates/` with
  `_subdirectory`, preserving Git template metadata for future `copier update` runs. Copying a
  nested template path directly renders files but cannot record an updateable monorepo template
  revision. `multi-tenant` remains a direct, non-updateable README seed until the external
  Stronghold round-trip prerequisite exists.
- `dry_run`: when true, only print commands.

### Extended fields (schema v1)

Used by `InstallAnswersV1` (Pydantic) and `POST /v1/install/plan` in Hive Conductor. See [SPEC-180](../specs/SPEC-180-maistro-install-bootstrap.md).

| Key | Type | Purpose |
|-----|------|---------|
| `schema_version` | `"1"` | Version gate for golden tests / API parity. |
| `install_mode` | `preview` \| `apply` | Informational; CLI `--apply` controls execution. |
| `llm_gateway` | `litellm` \| `direct` \| `other` | Intent; `other` → preview note until wired. |
| `observability_backend` | `none` \| `langfuse_v2` \| `langfuse_v3` \| `arize` | Intent; `arize` → preview note until compose fragment exists. |
| `deployment_tier` | `local_docker` \| `local_podman` \| `vm` \| `lxc` \| `proxmox` \| `bare_metal` | Wizard / docs; not auto-installed. |
| `container_runtime` | `docker` \| `podman` \| `auto` | Selects binary in `apply_spec` when `stack_bringup` is `root_full`. |
| `users_intent` | `bootstrap_admin` \| `sso_later` \| `skip` | See [USERS-AND-AGENTS.md](./USERS-AND-AGENTS.md). |
| `stack_bringup` | `none` \| `root_full` | `root_full` → `apply_spec` with `docker compose build --pull never` from repo root when root is detected (`compose up` is manual). |
| `provider_accounts` | map[str, bool] | Which vendors you plan to use — **never** store API keys here. |

Examples: [examples/answers-v1-minimal.yaml](./examples/answers-v1-minimal.yaml), [examples/answers-v1-stack.yaml](./examples/answers-v1-stack.yaml).

Comparison prose: [comparisons/llm-gateway.md](./comparisons/llm-gateway.md), [comparisons/observability.md](./comparisons/observability.md).

**Session merge:** `merge_session_payload()` in `maistro_bootstrap.schema` merges a partial JSON object with defaults for Hive `POST /v1/install/session` and future CLI flags.

---

## Stronghold / external products

Do **not** add Stronghold code to `maistro-engine`. The installer should **print** clone/template instructions or run Copier against `templates/multi-tenant/` into a **target directory** chosen by the user.

---

## External prototypes (out of tree)

Installer and resolver docs intentionally **do not** embed frozen copies of sibling product or platform repos. If you need a convergence algorithm, gateway flow, or stack-specific compose: clone the relevant repository beside `maistro-engine`, document the path in a PR to this file or in [.cursor/context/README.md](../../.cursor/context/README.md), and keep **secrets and internal hostnames** out of committed YAML.

---

## Related docs

- [ADR-033: Templates and Copier workflow](../adr/ADR-033-templates-and-copier-workflow.md)
- Sibling products may document curl-based installers (`--dry-run`, TTY detection); mirror that UX in `maistro-install` where applicable.

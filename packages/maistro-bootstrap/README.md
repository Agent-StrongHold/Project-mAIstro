# maistro-bootstrap

Small CLI used from the **maistro-engine** repo root to:

- Run a **multi-step install wizard** (Questionary) or pass a **YAML answers file** (`InstallAnswersV1` per [SPEC-180](../../docs/specs/SPEC-180-maistro-install-bootstrap.md))
- Pick **feature slices** and optional **compose add-ons** (merged compose plans, e.g. Hive + Phoenix)
- Emit a structured **JSON plan** (`--json`) — same shape as Hive `POST /v1/install/plan`
- Print `uv`, `docker compose` (validate), **Podman** hints, `podman compose` (run), and `copier copy` commands
- Optionally run **compose build** only: `--apply` with `--no-dry-run` runs `docker compose build --pull never` or `podman compose build --pull never` from the **monorepo root** when `stack_bringup: root_full` and the repo root is detected (`MAISTRO_REPO_ROOT` or walk-up). Start containers with `compose up` yourself when ready.

## Setup

From repo root:

```bash
uv sync --extra bootstrap
uv run maistro-install --help
```

## Usage

Interactive (TTY):

```bash
uv run maistro-install
```

Headless:

```bash
uv run maistro-install --answers-file docs/install/examples/answers-v1-minimal.yaml
```

Structured plan (Tier 0 / CI / Hive parity):

```bash
uv run maistro-install --answers-file docs/install/examples/answers-v1-stack.yaml --json
```

Print-only (default; no subprocesses):

```bash
uv run maistro-install --dry-run --answers-file docs/install/examples/answers-v1-minimal.yaml
```

Apply **only** `compose build --pull never` when answers request `stack_bringup: root_full`:

```bash
uv run maistro-install --answers-file docs/install/examples/answers-v1-stack.yaml --no-dry-run --apply --yes
```

See [docs/install/resolver-matrix.md](../../docs/install/resolver-matrix.md) for checkbox ids, compose add-ons, and extended answers fields.

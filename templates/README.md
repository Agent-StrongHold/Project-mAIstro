# Copier templates (ADR-033)

This directory holds **scaffold** templates for the three product peers. Each subdirectory is a Copier project with its own `copier.yml`.

- **single-tenant-multi-user** — Conductor-shaped knobs (see ADR-033).
- **autonoetic** — autonoetic-agent-shaped knobs.
- **multi-tenant** — Stronghold-shaped knobs.

Bootstrap round-trip and CI render tests are tracked in [BACKLOG.md](../BACKLOG.md) (engine-010–012). Expand each template with real `pyproject.toml`, compose, and `src/` overlays in follow-up PRs.

Use from repo root:

```bash
uv tool install copier
copier copy templates/single-tenant-multi-user ./out/my-product --trust
```

Or run `uv run maistro-install` and pick a product to print the same command.

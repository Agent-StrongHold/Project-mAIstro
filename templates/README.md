# Copier templates (ADR-033)

This directory holds Copier projects for the product variants described by ADR-033.

- **single-tenant-multi-user** — runnable Conductor-shaped scaffold with
  deployment, governance, and contract-test wiring.
- **autonoetic** — runnable Turing-shaped scaffold with deployment, governance,
  and contract-test wiring.
- **multi-tenant** — question/README seed only. Completing and round-tripping it
  is blocked on the external Stronghold target; do not treat it as runnable.

Render and update coverage for the completed templates lives under
[`tests/templates/`](../tests/templates/). The multi-tenant follow-up remains
tracked as `engine-012` in [BACKLOG.md](../BACKLOG.md).

Use from repo root:

```bash
uv sync
uv run copier copy --data product_template=single-tenant-multi-user . ./out/my-product
```

Using the repository root is required for update metadata: Copier stores the
Git ref and the root dispatcher selects the payload through `_subdirectory`.
After committing the generated product, future template releases can be
applied with `uv run copier update`.

Or run `uv run maistro-install` and pick a product to print the same command.

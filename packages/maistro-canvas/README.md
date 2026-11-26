# maistro-canvas

Standalone **book builder** with an AI image-generation pipeline: a phased
illustration service (brief → explore → render → assemble) that runs on modest
hardware alongside a local image-generation server.

Built on the canvas protocols from `maistro-core`; ships a FastAPI service,
the Davinci agent, and a frontend under `frontend/`. Part of the maistro-engine
monorepo and released in lockstep with the root `VERSION` file
(ADR-073126-c4e1); it builds in CI but is not published to PyPI — the shipped
form is the `maistro-engine` container image and this source package.

## Development

```bash
uv sync --locked
uv run pytest packages/maistro-canvas/tests
```

# maistro-rsi

Recursive self-improvement on the agent's own codebase: agents that branch,
patch, and benchmark candidate changes inside isolated microVM sandboxes
(`MicroVmSandbox` protocol), then promote only governed winners.

Wires together the monorepo's sandbox execution environment, the
`maistro-evolve` fitness machinery, and `maistro-bootstrap` builders.
Part of the maistro-engine monorepo and released in lockstep with the root
`VERSION` file (ADR-073126-c4e1).

## Development

```bash
uv sync --locked
uv run pytest packages/maistro-rsi/tests
```

# maistro-evolve

Elo tournament optimizer for agent self-improvement: a genome-evolution
pipeline (crossover, mutation, tournament selection, fitness scoring) run
against named benchmarks, with governed promotion of winning candidates.

Behavior inventory: SPEC-202 / v1 release plan D3 (#291). Part of the
maistro-engine monorepo and released in lockstep with the root `VERSION`
file (ADR-073126-c4e1).

## Development

```bash
uv sync --locked
uv run pytest packages/maistro-evolve/tests
```

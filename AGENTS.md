# maistro-engine agent bootstrap

This file is intentionally small. Repository operating knowledge uses progressive disclosure.

## Start here

Read [`docs/agent-guidance/README.md`](docs/agent-guidance/README.md), then load only the domain index and atomic documents applicable to the task. Do not preload the full guidance, ADR, or specification corpus.

## Universal constraints

- Never commit secrets, credentials, or `.env` files.
- Do not hand-edit externally managed rules under `.cursor/rules/imported/`.
- Treat `docs/adr/` and `docs/specs/` as canonical records in place; use the routing/index layer to discover what applies.
- For pre-1.0 work, optimize for the intended 1.0 architecture rather than preserving historical compatibility unless that compatibility independently belongs in the target design.
- When repository guidance conflicts, surface the conflict and follow the precedence defined by the agent-guidance router and its canonical sources.

## Task routing

- Development lifecycle, autonomy, compatibility, or CI principles: [`docs/agent-guidance/development-standards/`](docs/agent-guidance/development-standards/README.md)
- Human/agent authority, delegation/OBO, trust, or development threat model: [`docs/agent-guidance/authority-and-agency/`](docs/agent-guidance/authority-and-agency/README.md)
- Repository structure, style, commands, contribution mechanics, migrations, or documentation conventions: [`docs/agent-guidance/repository-standards/`](docs/agent-guidance/repository-standards/README.md)
- Normative behavior or acceptance requirements: route through specifications from [`docs/agent-guidance/README.md`](docs/agent-guidance/README.md)
- Architecture or cross-product contract decisions: route through ADRs from [`docs/agent-guidance/README.md`](docs/agent-guidance/README.md)

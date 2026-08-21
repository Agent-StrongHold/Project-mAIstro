---
id: ADR-062326-616c
title: "Design skills code export capability — React/TSX output format"
repo: maistro-engine
kind: adr
status: Implemented
created: 2026-06-23
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-019
  - maistro-engine#ADR-031
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-23
  - status: Implemented
---

# ADR-062326-616c — Design skills code export capability

## Context

`maistro-design` currently generates design artifacts (HTML, Markdown, images) via `DesignEngine.generate()`, which builds a prompt stack grounded in skill instructions + design system tokens. The `PROTOTYPE` and `TEMPLATE` skill modes emit static HTML — no real component code suitable for production use.

This gap prevents the design workflow from reaching parity with modern AI-assisted design tools (e.g., Subframe) that can emit production-grade React/TypeScript components. Generating runnable code — not just markup — opens two paths:

1. **Immediate:** LLM-emitted React components grounded in the design system's tokens and typography scale, sandboxed in preview before integration.
2. **Future:** Curated component primitives (Subframe's @subframe/core model) that the LLM composes deterministically instead of free-form generation.

## Decision

### 1. Add `OutputFormat.REACT_TSX` enum value

Extend `maistro_design.types.OutputFormat` with `REACT_TSX = "react_tsx"`. This signals that a skill is capable of emitting React component code.

### 2. Extend prototype/template skills with code output capability

Update built-in skills (`login-flow`, `agent-browser`, `landing-page`, `email-template`) to declare:
```python
output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX]
```

Update their `system_prompt` to instruct LLMs to emit a self-contained `.tsx` module:
- Default export is a React component (functional, not class).
- Uses Tailwind utility classes exclusively (no inline styles or CSS modules).
- Imports React, only standard library and Tailwind.
- Includes JSDoc comment with discovery response summary.
- No external API calls; interactive state uses local `useState()`.

### 3. Trust handling: code output inherits project trust tier

A `DesignProject` with `trust_tier=T3` (untrusted user discovery input) produces code that is also `T3` and must pass a new Warden scan before rendering/preview. This scan is implemented downstream (not in this ADR), but the trust tier flows through cleanly.

### 4. No canvas auto-creation for code output

Unlike `IMAGE`/`TEMPLATE` modes (`engine.py:178`), `REACT_TSX` output does not auto-create a `CanvasRecord`. Code artifacts are stored by downstream callers (project workspace or separate artifact store).

## Consequences

### Positive
- Design skills now span from wireframe (HTML) to production (React).
- Discovery forms continue to eliminate "regenerate with different style" loops.
- Prompt stack includes all trust-relevant context (system prompt + design tokens + discovery responses).

### Negative / Trade-offs
- LLM-generated code is a new untrusted surface. Downstream (hive-conductor, canvas-frontend) must add code-specific Warden scanning before preview/use.
- No determinism guarantee. Free-form generation produces varied code quality; Subframe's curated-component model (future) would be more reliable.
- Preview surface (sandboxed iframe + bundler) is new infrastructure, not in scope for this ADR.

### Neutral
- `OutputFormat` enum grows by one value; non-breaking change to existing code.
- Formal property tests (Hypothesis) remain unchanged; they iterate skills by mode, not output format.

## Out of scope

- LLM call and code-scanning orchestration (downstream concern).
- Component library / design-system-as-code (@subframe/core evaluation).
- Preview/sandboxing surface in hive-conductor or canvas-frontend.
- Performance optimization of code generation.

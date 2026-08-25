---
id: SPEC-062326-e9c6
title: "Design skills React/TSX output format — acceptance criteria"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-23
substrate:
  - maistro-engine#ADR-062326-616c
implements:
  - maistro-engine#ADR-062326-616c
related:
  - maistro-engine#SPEC-160
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_design.py
ac-modules:
  AC-1: maistro_design.types
  AC-2: maistro_design.skills.builtins
  AC-3: maistro_design.skills.builtins
  AC-4: maistro_design.skills.builtins
  AC-5: maistro_design.skills.builtins
  AC-6: maistro_design.skills.builtins
  AC-7: maistro_design.skills.builtins
  AC-8: maistro_design.engine
  AC-9: maistro_design.engine
  AC-10: maistro_design.engine
  AC-11: maistro_design.engine
  AC-12: maistro_design.engine
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-23
  - status: Implemented
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# SPEC-062326-e9c6 — Design skills React/TSX output format

## Context

ADR-062326-616c introduces `OutputFormat.REACT_TSX` to enable design skills to emit production-grade React component code. This spec defines the acceptance criteria for that capability across types, skills, and engine behavior.

## Goals

- Define the exact shape and constraints of React/TSX output.
- Ensure design skills correctly declare code output capability.
- Verify that `DesignEngine.generate()` builds prompts that guide LLMs toward valid, testable code.
- Establish trust handling for code artifacts.

## Non-goals

- LLM call orchestration (downstream).
- Code scanning / sandboxing (downstream).
- Component library evaluation or design-token-as-code patterns.

## Decision

### OutputFormat enum

```python
class OutputFormat(StrEnum):
    HTML = "html"
    MARKDOWN = "markdown"
    PPTX = "pptx"
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"
    CSS = "css"
    JSON = "json"
    REACT_TSX = "react_tsx"  # ← NEW
```

### Built-in skills: output format declaration

#### login-flow (PROTOTYPE mode)
```python
DesignSkill(
    slug="login-flow",
    name="Login Flow",
    mode=SkillMode.PROTOTYPE,
    output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],  # ← declare both
    system_prompt="""...[existing prompt]...\n\n## Code Output Instructions\n[guidance]""",
    ...
)
```

#### agent-browser (PROTOTYPE mode)
```python
DesignSkill(
    slug="agent-browser",
    name="Agent Browser UI",
    mode=SkillMode.PROTOTYPE,
    output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],
    system_prompt="""...[existing prompt]...\n\n## Code Output Instructions\n[guidance]""",
    ...
)
```

#### landing-page (TEMPLATE mode)
```python
DesignSkill(
    slug="landing-page",
    name="Landing Page",
    mode=SkillMode.TEMPLATE,
    output_formats=[OutputFormat.HTML, OutputFormat.CSS, OutputFormat.REACT_TSX],
    system_prompt="""...[existing prompt]...\n\n## Code Output Instructions\n[guidance]""",
    ...
)
```

#### email-template (TEMPLATE mode)
```python
DesignSkill(
    slug="email-template",
    name="Email Template",
    mode=SkillMode.TEMPLATE,
    output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],
    system_prompt="""...[existing prompt]...\n\n## Code Output Instructions\n[guidance]""",
    ...
)
```

### System prompt extensions

Each skill's `system_prompt` gains a "## Code Output Instructions" section:

```
## Code Output Instructions

When the user requests React/TSX output:

1. Generate a single, self-contained `.tsx` file that exports a default React component.
2. Use functional components and React hooks (useState, useEffect). No class components.
3. Style exclusively with Tailwind utility classes. No CSS-in-JS, no CSS modules, no inline styles.
4. Import only:
   - `react` (React, useState, useEffect, etc.)
   - Tailwind CSS (already available in the rendering environment)
5. Do not make external API calls. Use local state for all interactivity.
6. Include a JSDoc comment at the top with the component's purpose and discovery response summary.
7. Ensure the component is accessible (ARIA labels, semantic HTML, keyboard navigation).
```

### Trust tier flow

- A `DesignProject` with `trust_tier=T3` (untrusted discovery responses) produces `DesignOutput` with `trust_tier=T3`.
- Code output inherits the project's trust tier — downstream callers must scan it before rendering.
- No automatic trust upgrade based on output format.

### Engine behavior: no canvas auto-creation

`DesignEngine.generate()` currently creates a `CanvasRecord` for `IMAGE`/`TEMPLATE` modes:

```python
if self._canvas_store is not None and skill.mode in (SkillMode.IMAGE, SkillMode.TEMPLATE):
    canvas_record = ...
    canvas_id = canvas_record.id
```

For `REACT_TSX` output: do **not** auto-create a canvas record. The skill mode determines canvas creation, not the output format. (Future: a downstream service may store the artifact separately.)

## Acceptance criteria

### OutputFormat enum

```gherkin
@AC-1
Scenario: REACT_TSX value exists in OutputFormat
  When OutputFormat.REACT_TSX is accessed
  Then its value is "react_tsx"
  And it is a valid StrEnum member
```

### Built-in skills declaration

```gherkin
@AC-2
Scenario: login-flow declares HTML and REACT_TSX output
  Given an InMemoryDesignSkillRegistry with load_builtins() called
  When registry.get("login-flow") is called
  Then skill.output_formats contains OutputFormat.HTML
  And skill.output_formats contains OutputFormat.REACT_TSX

@AC-3
Scenario: agent-browser declares HTML and REACT_TSX output
  Given an InMemoryDesignSkillRegistry with load_builtins() called
  When registry.get("agent-browser") is called
  Then skill.output_formats contains OutputFormat.HTML
  And skill.output_formats contains OutputFormat.REACT_TSX

@AC-4
Scenario: landing-page declares HTML, CSS, and REACT_TSX output
  Given an InMemoryDesignSkillRegistry with load_builtins() called
  When registry.get("landing-page") is called
  Then skill.output_formats contains OutputFormat.HTML
  And skill.output_formats contains OutputFormat.CSS
  And skill.output_formats contains OutputFormat.REACT_TSX

@AC-5
Scenario: email-template declares HTML and REACT_TSX output
  Given an InMemoryDesignSkillRegistry with load_builtins() called
  When registry.get("email-template") is called
  Then skill.output_formats contains OutputFormat.HTML
  And skill.output_formats contains OutputFormat.REACT_TSX
```

### System prompt content

```gherkin
@AC-6
Scenario: Prototype skills include "Code Output Instructions" in system_prompt
  Given an InMemoryDesignSkillRegistry with load_builtins() called
  When registry.get("login-flow").system_prompt is examined
  Then it contains the string "Code Output Instructions"
  And it contains guidance for functional components
  And it contains guidance for Tailwind styling
  And it mentions "no external API calls"

@AC-7
Scenario: Template skills include "Code Output Instructions" in system_prompt
  Given registry.get("landing-page").system_prompt
  Then it contains the string "Code Output Instructions"
  And functional component guidance is present
```

### Trust tier inheritance

```gherkin
@AC-8
Scenario: REACT_TSX output inherits project trust tier
  Given a DesignEngine and a DiscoveryResult with trust_tier=T3
  When generate(discovery) is called for "login-flow" in REACT_TSX mode
  Then project.trust_tier == T3
  And project.outputs[0].trust_tier == T3

@AC-9
Scenario: Code output does not auto-upgrade trust
  Given a T2 skill and T0 design system
  And a DiscoveryResult with T3 responses
  When generate(discovery) is called
  Then project.trust_tier == T3 (the minimum)
  And output.trust_tier == T3
```

### Canvas behavior: no auto-creation for code

```gherkin
@AC-10
Scenario: PROTOTYPE mode does not auto-create canvas
  Given a DesignEngine with canvas_store provided
  And a DiscoveryResult for "login-flow" (PROTOTYPE mode)
  When generate(discovery) is called
  Then project.canvas_id is None (no auto-creation)

@AC-11
Scenario: TEMPLATE mode with code output still does not auto-create canvas
  Given a DesignEngine with canvas_store provided
  And a DiscoveryResult for "landing-page" (TEMPLATE mode)
  When generate(discovery) is called
  Then project.canvas_id is None (canvas creation is mode-driven, not format-driven)

@AC-12
Scenario: IMAGE mode still auto-creates canvas (existing behavior unchanged)
  Given a DesignEngine with canvas_store provided
  And a DiscoveryResult for "hero-image" (IMAGE mode)
  When generate(discovery) is called
  Then project.canvas_id is not None (unchanged)
```

## Testing

Unit tests live in `packages/maistro-design/tests/test_design.py` and implement all Gherkin scenarios above.

Formal property tests (Hypothesis, `formal/models/test_design_registry_state.py`) iterate by skill mode, not output format — no changes needed.

## Open questions

- Should REACT_TSX output optionally declare a TypeScript interface for props (for downstream type safety)?
- Should the engine pre-validate LLM-generated code (e.g., syntax check)? (Answer: downstream concern, deferred.)

## References

- ADR-061: maistro-design package
- ADR-062326-616c: code export capability decision
- SPEC-160: maistro-design acceptance criteria

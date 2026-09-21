---
id: ADR-091726-7c2a
title: "A conversation, not a form or a guess, precedes every Goal and CreativeBrief commit"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-17
accepted: 2026-09-17
substrate:
  - maistro-engine#ADR-061
implements: []
related:
  - maistro-engine#ADR-060
  - maistro-engine#SPEC-192
  - maistro-engine#ADR-091626-ba4f
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/agents/test_brief_interview.py
  - packages/hive-conductor/backend/tests/test_program_brief_routes.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-17
  - status: Accepted
    date: 2026-09-17
---

# ADR-091726-7c2a: A conversation, not a form or a guess, precedes every Goal and CreativeBrief commit

## Context

The persistent Workspace Agent (#804, #53) takes intent from a person and
turns it into Goals it is accountable for. A Goal is a desired state with a
success condition and a stop condition (`docs/architecture/INTEROP-ONTOLOGY-v1.md`,
#458). A CreativeBrief is the versioned creative projection of one Goal
revision: audience, channel, source truth, allowed claims, requested
deliverables (`docs/product/DESIGN-STUDIO.md`, #774).

"Let's make a new video, let's start drafting a storyboard" carries none of
that. Two failure modes were observed while building the Content Studio
interaction (the demo attached to ADR-091626-ba4f):

1. The agent refused, because nothing in the record answered the request.
   Correct about the record, wrong about the agent: new work is its job.
2. The agent minted a Goal from the sentence with two multiple-choice chips.
   That is a form, and a form asks everything at once whether or not the
   record already knows it, cannot take "you decide" on one field and refuse
   it on another, and leaves the person unable to say "actually, YouTube"
   without starting over.

ADR-061 introduced discovery forms for design skills because "structured
upfront input eliminates redirect loops". SPEC-192 §Stage 1 then chose a
one-question-at-a-time interview over a form for persona authoring. Neither
said what happens between "make a video" and a Goal.

## Decision

**Every Goal and CreativeBrief the Workspace Agent commits is preceded by a
requirements interview, and nothing is written until the person confirms it.**

The interview has these properties, and they are the contract:

1. **One required question at a time, in plain words**, in a script order.
   Optional fields are never asked as gates; they show their defaults.
2. **The record answers first.** Anything the opening turn or the workspace
   record already answers is never asked. The record never overrides an
   answer the person gave.
3. **Free text, not chips.** An answer that matches a field's recognised
   options is recorded as that option; one that matches nothing is carried
   verbatim, never rejected.
4. **Answers go where they belong.** An answer that fits a different open
   field is recorded there and the current question stands.
5. **A default only where one is defensible.** "You decide" takes a marked
   default for a field that has one and is refused for a field that does
   not (there is no defensible default for what a video is about).
6. **Anything can be changed; nothing needs undoing.** "Change *field*"
   re-answers any field; "never mind" drops the interview, and because no
   Goal, brief or run was written, there is nothing to undo.
7. **Commit is a gate, not a step.** The draft a Goal revision and a
   CreativeBrief version are written from is produced only when every
   required field is known, and it carries the source of every field
   (person, verbatim, record, assumed) and the list of assumed fields, so the
   Goal's why-panel can cite them.

The interview is deterministic. A model may paraphrase the questions; the
fields, the routing and the gate do not depend on one, so the behaviour is
the same on every run and testable without a provider.

## Consequences

- SPEC-091726-7c2a implements this as `maistro.agents.brief_interview` and
  Hive's `/v1/program/brief` endpoints, beside the onboarding interview the
  program hyperagent already hosts. The first script is a video brief for
  creator workspaces.
- The Goal and CreativeBrief writers (#458, #774), when they exist, consume
  the gate's draft. Nothing upstream may mint a Goal from an interview the
  gate would not commit.
- Persona-declared scripts (a `briefs:` block beside `PersonaTemplate.interview`)
  are a follow-up; the script shape is data already.
- The Workspace Agent chat (#53) hosts the interview as ordinary turns; the
  Content Studio demo shows the intended shape, including the "brief so far"
  panel that `brief_summary` feeds.

## Alternatives considered

- **A discovery form (ADR-061).** Right for a design skill invoked with a
  known shape; wrong for chat, for the reasons in Context.
- **Let the model ask.** Non-deterministic, untestable, and the failure mode
  is exactly the one observed: it either refuses or guesses.
- **Commit first, refine later.** Creates a Goal with no success or stop
  condition, which the ontology says is not a Goal, and makes "never mind"
  an undo instead of a no-op.

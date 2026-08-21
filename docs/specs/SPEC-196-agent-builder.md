---
id: SPEC-196
title: Agent Builder — structured definition + elicitation policy
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-02
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-032   # contracts as acceptance criteria
implements: []
related:
  - maistro-engine#ADR-092   # capability-vs-control posture (structured-core / free-text override)
  - maistro-engine#ADR-039   # external-adoption / INSPIRATIONS (AGENTS.md interop)
contracts: []
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-02
---

# SPEC-196: Agent Builder — structured definition + elicitation policy

## Context

The chat-UI agent builder was producing **soulless agents** — `{model, tools}` stubs
with no persona or prompt. The fix is a structured agent-definition that acts as a
**generation-completeness contract**, forcing the builder LLM to collect enough to
write a real prompt. The schema's job is a **guardrail on the generator**, *not* a
human-authoring burden (this resolves the "AGENTS.md minimal-spec" ergonomics tension
named in ADR-092: a structured core with a free-text override).

## Two authoring paths

- **Template** — for novices *and* as the contract the builder LLM must satisfy. The
  tiered schema below.
- **Free-text** — for experts: prose or a pasted `AGENTS.md` overrides the scaffold.
  AGENTS.md-interoperable (import + export).

## Schema (🔴 Required · 🟡 Recommended · ⚪ Allowed)

| Group | Fields |
|---|---|
| **Identity** | 🔴 name · 🔴 role/persona · 🟡 description · ⚪ icon/tags/audience |
| **Mandate** | 🔴 purpose · 🟡 goal / success-criteria · 🟡 scope / non-goals |
| **Voice** | 🟡 tone/speech · 🟡 output-format · ⚪ recommended phrases/topics · 🟡 banned phrases/topics |
| **Rules** (RFC-2119) | 🔴* must-do · 🟡 should/try · 🟡 never-do · 🟡 refusal/escalation |
| **Grounding** | 🟡 examples (few-shot) · ⚪ knowledge sources · ⚪ glossary |
| **Capabilities** | ⚪ tools · ⚪ sub-agents · *(standard: `model="auto"` router-picked, strategy auto-derived, trust/priority tiers)* |
| **Open** | ⚪ additional-instructions (appended last) |

\* `must-do` is required only if any rules exist.

**Required floor = the minimum that prevents a soulless agent:** `name + role + purpose`
(+ `must-do` when rules are present). **`banned phrases/topics` critical entries are
also enforced at the `gate`/`scan` node** — prompts are bypassable; defense in depth.

## Compilation

Structured fields → a deterministic template → the system prompt (shared `PREAMBLE`
prepended). Users can **preview the compiled prompt**. The free-text path bypasses the
template but can still be run through a completeness check.

## Elicitation policy (3 gears)

| Gear | Behavior | Backs off? |
|---|---|---|
| 🔴 **Required** | loop until populated — **hard gate; the builder may not emit the agent without them** | No |
| 🟡 **Recommended** | best-effort; push for each, **but stop on frustration** | Yes |
| ⚪ **Advanced** | **offer** "fine-tune further?" — opt-in | n/a |

Two refinements that keep it neither annoying nor low-quality:

1. **Infer-and-confirm, don't interrogate.** Draft each field from the user's intent
   and ask to confirm/edit — so clearing Required is mostly confirming a draft.
2. **Back off to defaults, not blanks.** On frustration, *keep* the inferred values,
   stop asking, and signpost the Advanced door. Quality survives impatience.

**Frustration signals** (a trend or explicit, never one short reply): explicit
("just make it" / "skip" / "you decide"); implicit (declining reply length, repeated
"idk", negative sentiment); budget (after N recommended questions, soften). The user
may say **"done" at any point** and still get a working agent — Required is always
either filled or inferred-and-confirmed.

## Why structured *here* (vs. free prose elsewhere)

The Required tier is an **acceptance contract** (ADR-032 flavor) for "is this a real
agent?" — and it is the builder LLM's output **signature** (`intent → definition with
Required complete`). That is what makes the result **validatable and optimizable**:
you cannot validate or optimize "write a good agent" against free text, but you can
against a filled contract.

## Status

Proposed.

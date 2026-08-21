---
id: ADR-070426-f2a0
title: "Optional external renderers as discoverable capability providers behind maistro-design"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-07-04
accepted: 2026-07-06
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
implements: []
related:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-062326-702b
  - maistro-engine#ADR-062326-616c
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-188
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
---

# ADR-070426-f2a0: Optional external renderers as discoverable capability providers

## Context

`maistro-design` deliberately stops at prompt-stack assembly: "DesignEngine builds
artifacts; it does not call an LLM" (ADR-061). Rendering a skill's output to a
finished artifact (HTML, PPTX, MP4) is delegated to a renderer the caller supplies.
Today no renderer ships, so `PROTOTYPE`/`DECK`/`video` skills resolve a prompt stack
but produce no artifact.

Separately, `maistro-canvas` is not merely an image tool — it is a **fixed-layout
page compositor**: positioned layers (`x, y, scale, rotation, z_index`) of
background / generated-image / graphic / **text-with-typography** kinds. That is the
anatomy of a slide, flyer, poster, card, or cover, and it flattens losslessly to
PNG/PDF and maps 1:1 to structured PPTX/HTML (text layers → editable text boxes,
image layers → pictures). Canvas can therefore be the **always-present, plugin-free
floor** for every *fixed-layout* format.

What canvas cannot be: a *reflowable/responsive* web renderer, or a video renderer.
Mature open-source tools already do those well — notably `nexu-io/open-design`
(Apache-2.0), whose Apache design-system corpus we already vendor (ADR-100), and
which runs as a local daemon exposing render endpoints.

The open question this ADR settles: do we reimplement decks/reflowable-web/video
ourselves, and how do we consume external tools without making them a hard
dependency or a source of runtime errors when absent?

## Decision

### 1. External renderers are optional capability providers, not dependencies

Model every renderer as a **provider that fills one or more capability slots** in
`maistro.capabilities` (slots / providers / registry / discovery, SPEC-184; re-probed
by the self-repair governor, SPEC-188). Slots:

- `renderer.fixed-page` — slide / flyer / poster / card / cover. **Canvas-native, always present.**
- `renderer.deck` — multi-page decks → PPTX/PDF. Canvas-native once exporters land; Open Design as alternate.
- `renderer.reflowable-web` — responsive HTML/CSS. **Open Design only** (canvas cannot reflow).
- `renderer.video` — HTML→MP4. **Open Design HyperFrames only.**
- `designsystems.live` — live design-system corpus (vs. the vendored ADR-100 snapshot).

### 2. Absence is silent; failure is not

A skill declares a `required_renderer` slot. Skill resolution filters to skills whose
slot is filled. A slot with **no discovered provider** means the skill is never
offered — no call site, nothing to fail, no error. A provider that is **discovered
but errors at render time** is a real fault: circuit-break it via `maistro.resilience`
(ADR-038), empty the slot until it recovers, and surface the error to the invoking
caller. Absence ≠ failure.

### 3. Rendering stays outside DesignEngine

The ADR-061 boundary holds: `DesignEngine` builds the prompt stack; a `RenderProvider`
(new protocol) consumes it and returns an `ArtifactNode` tree (ADR-062326-702b), which
is scanned (Warden/Sentinel) before becoming a `DesignOutput`.

### 4. Open Design is the first external provider

`nexu-io/open-design` fills `renderer.reflowable-web`, `renderer.deck`,
`renderer.video`, and `designsystems.live`, discovered by probing its local daemon.
Its outputs are third-party → trust tier T2 and scanned on ingest, consistent with how
the vendored corpus is tiered (ADR-100).

## Consequences

### Positive
- Zero-plugin installs are still a complete fixed-layout designer (canvas floor).
- No hard dependency on any external tool; features degrade to "absent," never to "error."
- Same discover-and-filter mechanism serves all product tiers: Agent Conductor lights up
  whatever is installed; Stronghold can policy-deny slots per tenant; a library import runs canvas-only.
- We integrate decks/web/video instead of reimplementing them.

### Negative / Trade-offs
- Two new surfaces to build and maintain: the capability substrate (SPEC A) and each
  provider integration (SPEC B), plus the canvas exporters (SPEC C).
- External provider outputs cross a trust boundary and must be scanned every time.
- A discovered-but-flaky provider adds resilience/circuit-breaker complexity.

### Neutral
- Skill catalogs become environment-dependent (what's offered depends on what's discovered).
- Establishes a provider pattern a second vendor (e.g. Presenton) can adopt later via a follow-on ADR.

## Implementing SPECs

- `maistro-engine#SPEC-070426-a22b` — renderer capability substrate + graceful absence.
- `maistro-engine#SPEC-070426-6ea8` — Open Design renderer provider.
- `maistro-engine#SPEC-070426-457b` — canvas structured exporters (PPTX/HTML).

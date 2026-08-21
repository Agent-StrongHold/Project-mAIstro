---
id: ADR-070426-3a1f
title: A2UI declarative agent-driven UI protocol adoption
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-058
related:
  - maistro-engine#ADR-083
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
  - maistro-engine#ADR-062326-702b
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-3a1f: A2UI declarative agent-driven UI protocol adoption

## Context

The engine has exactly one path for an agent to produce a user interface today, and it is the
wrong trust posture for a UI: `maistro-design` (ADR-061) builds a prompt stack, an LLM generates
**code** (`REACT_TSX`/`HTML`/`SVG` — `OutputFormat` in
`packages/maistro-design/src/maistro_design/types.py`), and `ArtifactNode` (ADR-062326-702b)
holds the result as a static, hierarchical output tree. Every renderer downstream of that is a
**rasterizer** — it turns the artifact into bytes (an image, a static page) — not a live,
updatable surface. `DesignSystem.components` (`types.py:171`) is a bare `list[str]`: a naming
convention for the LLM to imitate, not a schema anything can validate against or enforce. This is
"expressive like code," full stop; there is no "safe like data" half.

That gap matters because the engine already has the other half of the trust story built and
unused for UI: `TrustTier` (`maistro.types.security`, `SKULL < T4 < T3 < T2 < T1 < T0`) and the
Warden/Sentinel pair (ADR-083) exist precisely to bound what untrusted content is allowed to do
inside the runtime. Nothing currently maps that model onto "what components can an agent ask a
client to render."

Separately, the project has already committed to solving this with **A2UI** (`/home/user/A2UI`,
Apache-2.0, a fork of Google's A2UI project) without ever formalizing the decision:

- BACKLOG `[engine-090]` — chat-UI integration contract: OpenAI-compatible chat completions **+
  A2UI for rich UI generation + MCP for tools**, tested against OWUI/LibreChat/Lobe Chat as
  render targets, and named specifically as a way to defuse Open WebUI's 50-user attribution
  clause for Stronghold tenants by allowing an alternative UI per tenant.
- BACKLOG `[engine-091]` — pin A2UI to a specific tag in the engine's Copier templates.
- BACKLOG `[sh-602]` — A2UI render layer for Stronghold tenants, implementing `[engine-090]` at
  the tenant level.
- `SPEC-179` FR-5 (Canvas gateway) already assumes A2UI: "WebView loads canvas and A2UI URLs
  provided by the gateway."

Three separate backlog items and a shipped spec all lean on A2UI, yet no ADR, no SPEC, and no
code exist for any of it. This ADR closes that gap.

### What A2UI is

A2UI is a protocol plus reference libraries that let an agent "speak UI": it sends declarative
JSON describing a component tree (an **adjacency list** — flat, id-referenced, LLM-streamable and
incrementally patchable) and a separate JSON **data model**, bound via JSON Pointer (RFC 6901).
Client-side renderers (React, Lit, Angular, Flutter via the GenUI SDK) map that abstract tree to
native widgets. The project's own framing is exact: **"safe like data, expressive like code."**
The safety mechanism is a **catalog** — a JSON Schema enumerating the components, functions, and
theme properties a given client renderer supports. An agent may only reference components in the
catalog the client has advertised (`v0_10` catalog negotiation, `supportedCatalogIds`); anything
outside the catalog cannot be expressed, by construction, not by runtime policing after the fact.

Key surfaces relevant to this decision (see `specification/v0_10/README.md` and
`docs/concepts/*.md` in `/home/user/A2UI`):

- **Surfaces** — addressable UI regions (`surfaceId`), created/updated/torn down via
  `createSurface` / `updateComponents` / `updateDataModel` / `deleteSurface`
  (`specification/v0_10/json/server_to_client.json`).
- **Actions** — client→server `event` (round-trips to the agent) vs. local `functionCall`
  (executed entirely on the renderer, e.g. `openUrl`); renderer-side `checks` gate interactive
  components before an event is even sent.
- **Transport** — A2A extension URI `https://a2ui.org/a2a-extension/a2ui/v0.10` (a `DataPart` with
  `mimeType: application/json+a2ui`), or AG-UI/SSE/WebSocket.
- **Python agent SDK** (`agent_sdks/python/src/a2ui/`) — `A2uiSchemaManager` (generates the LLM
  system prompt from a catalog), `A2uiValidator` (pre-send schema validation), a streaming
  parse-and-heal JSON fixer (`payload_fixer.py`), and A2A extension helpers.

## Decision

### 1. Adopt A2UI as the engine's declarative agent-driven UI protocol, pinned at v0.10

This closes `[engine-090]` and `[engine-091]` as designed-not-just-committed. v0.10 is the pinned
baseline (the newest spec directory in `/home/user/A2UI/specification/`); the engine does not track
`main` — version bumps are a deliberate, reviewed action, following the same "pin, don't float"
posture the engine already takes with other vendored substrate (e.g. ADR-100's Open Design
corpus pinned by source commit).

### 2. A2UI is additive, not a replacement for maistro-design's codegen path

`maistro-design` keeps generating code artifacts (marketing pages, illustrations, print-ready
output) — that is a legitimate, different use case: a one-shot rasterized artifact, not a live
interactive surface. A2UI is for the case ADR-061 does not cover: an agent that needs to render
an **updatable, interactive** UI region inside a chat/session — forms, dashboards, approval
flows, booking widgets — where the client (not the agent) owns execution.

### 3. Integrate the Apache-2.0 Python SDK behind an engine protocol, never imported directly

Per the engine's no-direct-imports DI rule (mirrored from Stronghold's Build Rule #5 and the
existing `HarnessRunner` precedent, `maistro.capabilities.protocols.HarnessRunner`), business
logic never imports `a2ui` directly. A new `maistro.protocols` interface —
`A2uiSurfaceRenderer` / `A2uiValidator` in shape — wraps the reusable parts of the vendored SDK:

- Schema-manager prompt generation (turns a catalog into the system-prompt fragment an agent
  needs to emit valid A2UI JSON for it).
- The streaming parse-and-heal JSON fixer (directly reusable for the same reason the engine
  already streams and incrementally patches other LLM output).
- `A2uiValidator` schema validation, run agent-side before send (mirrors A2UI's own two-phase
  validation strategy) and swapped for a `NoopA2uiValidator` fake in tests, following the
  "every protocol needs a noop/fake" convention.

No other part of the SDK (renderers, transport bindings) is imported into engine business logic;
see Non-goals.

### 4. Catalog approval maps onto `TrustTier`

An A2UI **catalog** is structurally the same problem the engine already solved for skills
(ADR-083) and design systems (ADR-100): a schema of things an agent is allowed to reference,
sourced partly from the engine (built-in) and partly from installed/community content, with a
review workflow for anything not built-in. This ADR decides that a catalog is registered with a
`TrustTier` exactly as `DesignSystem` and `DesignSkill` are:

- Catalogs shipped by the engine (the A2UI Basic Catalog, and any first-party catalog mirroring
  an engine `DesignSystem`) register at `T0`.
- Catalogs vendored from a reviewed, scanned third-party source (mirroring ADR-100's Tier-1 Open
  Design import) register at `T1`.
- Caller-registered or community catalogs register at `T2` and route through the existing trust
  review queue (ADR-061 §4/§5 — Warden scan, async `TrustReviewRecord`, RLPHD feedback loop) before
  an admin can promote them.
- An unreviewed or banished catalog cannot be selected during A2UI catalog negotiation — the
  engine-side of negotiation refuses to advertise it, the same way ADR-083 refuses to install an
  unsigned skill.

This is the mechanism that lets `[sh-602]`'s per-tenant render layer exist without inventing a new
trust primitive: a tenant enables a catalog the same way it enables a skill or a design system.

### 5. Reserve the A2A `a2ui` extension slot in ADR-058 delegation flows

ADR-058 defines in-process and federated A2A delegation but says nothing about a delegated
sub-agent returning a UI surface instead of (or alongside) a text result. This ADR reserves the
A2A extension URI `https://a2ui.org/a2a-extension/a2ui/v0.10` as a recognized extension in
`A2ATask` / `AgentCard` capability negotiation, so a sub-agent can advertise A2UI support and an
orchestrator can route `action` events (client→server) back to the surface-owning sub-agent using
the same ownership-mapping pattern A2UI itself documents for multi-agent orchestrators
(`docs/concepts/actions.md` — "Surface Ownership Pattern," data-model stripping to prevent
cross-agent state leakage). Concrete wiring (session-state ownership map, metadata-stripping
interceptor) is SPEC-277's job, not this ADR's.

## Alternatives considered

**Build an engine-native declarative UI format.** Rejected. The engine would own a schema, a
validator, and — critically — client renderers for every target (web, Flutter/mobile gateway per
SPEC-179) with none of the ecosystem A2UI already has (CopilotKit/AG-UI, Lit, Angular, the
Flutter GenUI SDK). This is exactly the kind of "aesthetic decomposition" multi-agent-for-isolation
principle warns against, applied to protocols instead of agents: building bespoke where an
Apache-2.0 standard already fits.

**Extend `ArtifactNode` (ADR-062326-702b) into a live surface type.** Rejected. `ArtifactNode` is
deliberately a static output container — file/blob/nested-container — with no notion of a running
client, a data model, or bidirectional events. Retrofitting liveness onto it would either break
its existing (already-shipped) contract or produce a parallel, incompatible surface type in the
same dataclass family. A2UI's surface/data-model split is a different, already-solved shape; the
two artifact kinds (static generated output vs. live interactive surface) should stay distinct
types with a shared trust model, not one overloaded type.

**Status quo — codegen only, no declarative path.** Rejected; this is the option BACKLOG has
already rejected three times over (`[engine-090]`, `[engine-091]`, `[sh-602]`) without anyone
writing it down. Leaving it undecided keeps SPEC-179's FR-5 pointing at a protocol the engine has
no ADR for, and leaves `[sh-602]`'s Open WebUI attribution workaround unimplementable.

## Consequences

**Positive:**
- Closes `[engine-090]`, `[engine-091]`, and unblocks `[sh-602]` with a designed, not improvised,
  contract.
- Gives the engine a live, interactive, agent-driven UI surface without building or maintaining
  renderers — reference-only reuse of an Apache-2.0 ecosystem (React/Lit/Angular renderers,
  Flutter GenUI SDK for SPEC-179's gateway WebView).
- Reuses the existing `TrustTier`/Warden/trust-review machinery for a new artifact kind (catalogs)
  instead of inventing a parallel approval mechanism.
- `A2uiValidator`/schema-manager reuse behind a protocol keeps the no-direct-imports DI rule intact
  while still getting the SDK's actual engineering value (streaming JSON healing, prompt
  generation) rather than reimplementing it.

**Negative:**
- A second UI-producing code path (declarative A2UI alongside codegen `maistro-design`) is more
  surface area to keep straight for callers deciding which to use; SPEC-277 must state the
  decision rule plainly.
- Catalog-as-trust-tiered-artifact is a new registry (however small) alongside skills and design
  systems — one more thing ADR-083's review queue has to triage.
- A2UI v0.10 is still pre-1.0 ("under development" per its own spec README); pinning trades
  stability today for a migration cost when the spec stabilizes toward v1.0. `[engine-091]`'s
  version-pin-in-Copier-templates mechanism is the intended mitigation.

**Risks:**
- Data-model isolation across delegated sub-agents (ADR-058 reservation, §5) is a real security
  boundary — A2UI's own docs flag "state scraping" as a named risk when an orchestrator fails to
  strip cross-surface data model metadata. SPEC-277 must specify the stripping interceptor, not
  leave it as an exercise for the implementer.
- Inbound `action` events are, structurally, untrusted client input re-entering the runtime; if
  SPEC-277 does not route them through the same Warden scan every other inbound request gets, this
  ADR's trust story has a hole at exactly the boundary it exists to close.

## Non-goals

- Porting A2UI client renderers (React/Lit/Angular/Flutter) into the engine or `hive-conductor`'s
  frontend. Renderers are reference-only; the canvas frontend and SPEC-179's Flutter gateway
  WebView consume upstream renderers directly.
- Any frontend implementation work (React components, WebView wiring). This ADR is a protocol and
  trust-boundary decision; frontend consumption is downstream of it.
- Mirroring A2UI's Hypothesis/conformance-style test suite into `formal/`. Worth doing once the
  SDK integration (Decision §3) actually lands, so the conformance tests have something to run
  against; deciding the shape of that suite now, before any code exists, is premature.
- Redesigning `maistro-design`/`ArtifactNode`. Both are unchanged by this decision.
- Defining the concrete request/response flow through `Conduit`, the catalog registry shape, or the
  action-event re-entry path. That is SPEC-277.

## References

- [ADR-062: Graph execution protocol](ADR-062-graph-execution-protocol.md)
- [ADR-058: Agent-to-agent (A2A) delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [ADR-083: Skills and MCP gateway trust](ADR-083-skills-mcp-trust.md)
- [ADR-061: maistro-design — composable design skills + design systems](ADR-061-maistro-design-package.md)
- [ADR-100: Bundled and cataloged Open Design design systems](ADR-100-bundled-open-design-systems.md)
- [ADR-062326-702b: Multi-modality design outputs and hierarchical artifact containers](ADR-062326-702b-multi-modality-design-outputs-hierarchical-artifact-containers.md)
- [SPEC-277: A2UI surface integration](../specs/SPEC-277-a2ui-surface-integration.md)
- BACKLOG `[engine-090]`, `[engine-091]`, `[sh-602]` — `BACKLOG.md`
- A2UI project: `/home/user/A2UI/README.md`, `docs/concepts/{overview,catalogs,actions,data-binding}.md`,
  `specification/v0_10/README.md`
- Seams: `maistro.types.security.TrustTier`, `maistro.capabilities.protocols.HarnessRunner`
  (DI-behind-a-protocol precedent), `packages/maistro-design/src/maistro_design/types.py:171`
  (`DesignSystem.components`), `packages/maistro-core/src/maistro/conduit.py`

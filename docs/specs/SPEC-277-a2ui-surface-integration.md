---
id: SPEC-277
title: "A2UI surface integration"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-070426-3a1f
related:
  - maistro-engine#ADR-058
  - maistro-engine#ADR-083
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
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
---

# SPEC-277: A2UI Surface Integration

## Finding addressed

ADR-070426-3a1f adopts A2UI (pinned v0.10) as the engine's declarative agent-driven UI protocol
but leaves the concrete flow undesigned: how a `Conduit` request produces A2UI messages, how a
component catalog is registered and trust-reviewed, and how client `action` events get back into
the runtime. BACKLOG `[engine-090]` (chat-UI integration contract), `[engine-091]` (version pin),
and `[sh-602]` (per-tenant render layer) all depend on this flow existing; today none of it does —
no code, no route, no catalog registry.

## Design

### 1. Where A2UI sits in the request pipeline

A2UI does not replace any stage of the Conduit pipeline (`classify → route → agent.handle`,
`packages/maistro-core/src/maistro/conduit.py`). It is an **output channel** an agent's strategy
may choose alongside (or instead of) a text response, and an **input channel** for events a
rendered surface sends back:

```
POST /v1/chat/completions  (existing OpenAI-compatible entry point, [engine-090])
  → Conduit.classify → Conduit.route → agent.handle()
      → strategy.reason() may emit an A2uiSurfaceUpdate alongside/instead of message content
      → response includes an `a2ui` payload (list of server→client messages) when present
  → client renders; user interacts
  → client posts an `action` event
      → re-enters the Conduit as a new request (Section 5) — not a side channel
```

An agent that never emits A2UI content is completely unaffected: the `a2ui` field is absent, and
existing OpenAI-compatible response shape is unchanged. This satisfies `[engine-090]`'s three-way
contract (OpenAI-compat + A2UI + MCP) without a parallel API surface.

### 2. `A2uiSurface` lifecycle

A new type, `maistro.types.a2ui.A2uiSurface`, tracks server-side surface state:

```python
@dataclass
class A2uiSurface:
    surface_id: str
    catalog_id: str            # must resolve in the CatalogRegistry (Section 3)
    session_id: str            # scope: tied to maistro.sessions, not global
    owner_agent: str           # agent_name that created it — surface ownership (Section 5)
    send_data_model: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    data_model: dict[str, Any] = field(default_factory=dict)
    status: Literal["active", "deleted"] = "active"
```

Lifecycle mirrors the A2UI v0.10 message set 1:1 — no engine-side reinterpretation:

| A2UI message | Engine action |
|---|---|
| `createSurface` | Validate `catalogId` resolves to a registered, non-banished catalog at or above the caller's minimum trust tier (Section 3); create `A2uiSurface`; persist under the session. |
| `updateComponents` | Validate the component list against the surface's bound catalog schema (`A2uiValidator`, Section 4) before it leaves the agent process. |
| `updateDataModel` | Apply the JSON-Pointer patch to `A2uiSurface.data_model`. |
| `deleteSurface` | Mark `status="deleted"`; further `action` events against a deleted surface are rejected (`SURFACE_NOT_FOUND`). |

Surfaces are scoped to a session (`maistro.sessions`), following the same TTL-pruning lifecycle as
session history — a surface does not outlive its session. Cross-session surface reuse is out of
scope (Non-goals).

### 3. Component catalog schema unified with `DesignSystem` tokens + per-catalog `TrustTier`

A new `A2uiCatalog` registry entry, structurally parallel to `DesignSystem`
(`maistro_design.types.DesignSystem`) and `DesignSkill`:

```python
@dataclass
class A2uiCatalog:
    catalog_id: str                 # URI convention per A2UI spec, e.g. "https://.../v1/catalog.json"
    schema: dict[str, Any]          # freestanding JSON Schema (components/functions/theme)
    trust_tier: TrustTier
    design_system_slug: str | None = None   # optional link to a DesignSystem for token reuse
    scan_status: Literal["clean", "flagged", "unscanned"] = "unscanned"
```

Trust assignment mirrors ADR-100's two-tier import exactly:

- **Built-in catalogs** (the A2UI Basic Catalog, or an engine-authored catalog) register at `T0`
  via `load_builtin_catalogs()`, analogous to `load_bundled()`.
- **Reviewed third-party catalogs** vendored and scanned at integration time register at `T1`.
- **Caller/community catalogs** register at `T2` by default via `register_catalog()`, and must pass
  `scan_catalog_content()` — the same content-scan family as ADR-100's
  `scan_design_system_content()` (script/eval/iframe injection, prompt-injection phrasing, large
  base64 blobs, Unicode steganography, disallowed external URLs) applied to the catalog's JSON
  Schema text rather than a design-systems bundle.
- A catalog that fails the scan, or has been explicitly banished, is refused registration —
  `CatalogBannedError` — with no "register anyway" path, matching ADR-083's skill posture.
- **Token unification**: when `design_system_slug` is set, the catalog's `theme` block is derived
  from that `DesignSystem`'s `tokens_css`/`colors`/`spacing` rather than hand-authored, so an A2UI
  surface and a `maistro-design` codegen artifact for the same brand render from one source of
  token truth.

Registered catalogs feed the existing ADR-061 trust review queue: a `T2` catalog registration
enqueues a `TrustReviewRecord` (async, non-blocking — the catalog is usable immediately at its
assigned tier, same as ADR-061 §4's discovery-response posture) for admin promotion to `T1`.

Catalog **negotiation** (client-advertised `supportedCatalogIds` vs. server-selectable catalogs) is
a straight pass-through of the A2UI v0.10 protocol: the engine only refuses to advertise/select a
catalog that is unregistered or below the caller's minimum trust tier. It does not reimplement
negotiation semantics.

### 4. Validation via `A2uiValidator` behind a protocol

Per ADR-070426-3a1f §3, no engine module imports the `a2ui` package directly. A protocol in
`maistro.protocols`:

```python
class A2uiValidator(Protocol):
    def validate(self, catalog: A2uiCatalog, message: dict[str, Any]) -> ValidationResult: ...

class A2uiSchemaPromptBuilder(Protocol):
    def build_system_prompt(self, catalog: A2uiCatalog) -> str: ...
```

The default implementation wraps the vendored SDK's `A2uiSchemaManager` / schema-validation logic;
a `NoopA2uiValidator` fake (always-valid) is provided for tests, per the "every protocol needs a
noop/fake" rule. Two validation points, matching A2UI's own defense-in-depth model:

1. **Agent-side, pre-send** — before an `updateComponents`/`createSurface` message leaves
   `agent.handle()`, `A2uiValidator.validate()` runs against the surface's bound catalog. A failure
   triggers the streaming parse-and-heal fixer (reused from the SDK, Section 6) or, failing that,
   a text-only fallback response — the agent never sends a payload it knows is invalid.
2. **Client-side** — unchanged from upstream A2UI; the renderer validates again and reports
   `VALIDATION_FAILED` back over the same channel as an `action` (Section 5), which the engine logs
   and, if repeated, surfaces to the owning agent for self-correction.

### 5. Inbound `action` events re-enter the Conduit as new requests

An `action` (client→server event, e.g. a button submit) is untrusted input arriving at a trust
boundary — no different in kind from a chat message. It is **not** handled as a side-channel RPC:

1. Client posts `{"action": {"name", "surfaceId", "sourceComponentId", "context", ...}}`.
2. The engine resolves `surfaceId → A2uiSurface.owner_agent` (surface ownership map, kept in
   session state — mirrors A2UI's own documented "Surface Ownership Pattern" for multi-agent
   orchestrators).
3. The action is converted into a synthetic Conduit request: `intent_hint` set to the owning
   agent's task type, message content built from `action.name` + `action.context` (and, if
   `sendDataModel` was enabled at `createSurface`, the surface's current `data_model`).
4. **This synthetic request is Warden-scanned exactly like any other inbound request** before it
   reaches `agent.handle()` — actions are not a trusted-because-structured exception to "all input
   is untrusted." A crafted `context` value is exactly as untrusted as free text.
5. If the session has surfaces owned by more than one agent, the data model attached to the
   synthetic request is filtered to the owning agent's surface(s) only (metadata-stripping,
   preventing the "state scraping" cross-agent leak the A2UI docs warn about).
6. The response re-enters the normal output path (Section 1) — it may itself contain further A2UI
   `updateComponents`/`updateDataModel` messages (patches, not full re-renders).

### 6. Streaming / patch semantics

A2UI's adjacency-list model is the reason this integration is viable for an LLM-driven runtime at
all: components are a flat, id-referenced list, so an agent emits `updateComponents` with only the
changed/added component ids — never a full-tree re-send. The engine reuses the SDK's streaming
parse-and-heal JSON fixer (`payload_fixer.py` upstream) behind the `A2uiValidator` protocol so that
partial/malformed JSON produced mid-stream by the LLM is repaired before validation, the same
tolerance the SDK itself is built for. `dataModelUpdate`/`updateDataModel` messages likewise carry
only the changed JSON-Pointer paths, not the full data model, except when `sendDataModel: true`
opts a surface into full-model sync on every client→server message (Section 5, step 3).

## Acceptance criteria

- [ ] AC-1: A `Conduit`-routed response with no A2UI content produced by the agent contains no
      `a2ui` field — existing OpenAI-compatible response shape is unchanged for non-A2UI agents.
- [ ] AC-2: `createSurface` against an unregistered `catalogId` is rejected before an `A2uiSurface`
      is created, with an error code distinguishable from `CATALOG_BANNED` (unregistered vs.
      banned are different failure modes).
- [ ] AC-3: `createSurface` against a catalog registered below the caller's minimum trust tier is
      rejected; the same request against a catalog at or above the minimum tier succeeds.
- [ ] AC-4: `register_catalog()` on a schema that fails `scan_catalog_content()` raises
      `CatalogBannedError` and does not add an entry to the registry.
- [ ] AC-5: A `T2`-registered catalog is immediately usable (non-blocking) and produces exactly one
      `TrustReviewRecord` queued for admin review.
- [ ] AC-6: `updateComponents` referencing a component name absent from the surface's bound
      catalog schema fails `A2uiValidator.validate()` before being sent to the client.
- [ ] AC-7: An `action` event is passed to `Warden` before it is dispatched to `agent.handle()` —
      a Warden-blocked action context produces the same refusal path as a Warden-blocked chat
      message, not a distinct code path.
- [ ] AC-8: An `action` event for a `surfaceId` that does not resolve to an owning agent in the
      current session returns `SURFACE_NOT_FOUND` and is not delivered to any agent.
- [ ] AC-9: In a session with surfaces owned by two different agents, the synthetic request built
      from an `action` on agent A's surface contains only agent A's surface data model — agent B's
      data model is absent (metadata-stripping).
- [ ] AC-10: `deleteSurface` sets `status="deleted"`; a subsequent `action` against that
      `surfaceId` returns `SURFACE_NOT_FOUND` rather than operating on stale state.
- [ ] AC-11: A catalog registered with `design_system_slug` set derives its `theme` block from that
      `DesignSystem`'s tokens rather than an independently authored theme.
- [ ] AC-12: `NoopA2uiValidator` (test fake) always returns valid, allowing agent-handling tests to
      run without the vendored SDK installed.
- [ ] AC-13: No module under `maistro.agents`, `maistro.conduit`, or `maistro.orchestrator` imports
      the `a2ui` package directly (grep-checkable) — all access is through
      `maistro.protocols.A2uiValidator` / `A2uiSchemaPromptBuilder`.

## Non-goals

- Client renderer implementation or bundling (React/Lit/Angular/Flutter) — reference-only, per
  ADR-070426-3a1f.
- Cross-session surface persistence/reuse — a surface's lifetime is bound to its session.
- Real-time multi-viewer/collaborative surface editing — tracked separately (ADR-101's
  "session co-ownership" follow-up), not this SPEC.
- MCP tool-call integration for A2UI `functionCall` actions — `functionCall` is renderer-local by
  protocol definition and never reaches the engine; only `event` actions do (Section 5).
- Stronghold tenant-scoping of catalogs (`[sh-602]`'s multi-tenant enable/disable) — this SPEC
  defines the single-tenant mechanism Stronghold's per-tenant policy layer sits on top of.
- Migrating off v0.10 toward A2UI's eventual v1.0 — tracked by `[engine-091]`'s version-pin
  mechanism, not designed here.

## Test plan sketch

- **Surface lifecycle**: unit tests creating/updating/deleting an `A2uiSurface` against a fake
  `CatalogRegistry`, covering AC-2, AC-3, AC-10.
- **Catalog registry + scan**: unit tests for `register_catalog()` against clean/flagged/malicious
  fixture schemas (script injection, oversized base64, zero-width Unicode), covering AC-4, AC-5,
  reusing the fixture style of `packages/maistro-design/tests/test_scan.py`.
- **Validator protocol**: tests using `NoopA2uiValidator` to prove `agent.handle()` never touches
  the real `a2ui` package (AC-12, AC-13, via import-boundary grep or `import-linter` contract), plus
  a real-validator test against a minimal catalog fixture for AC-6.
- **Action re-entry + Warden**: integration test posting a malicious `action.context` payload
  (prompt-injection string) and asserting it is scanned/blocked identically to a malicious chat
  message (AC-7).
- **Multi-agent isolation**: integration test with two agents each owning a surface in the same
  session, asserting data-model stripping on the synthetic request built from one agent's action
  (AC-9).
- **Design-system token unification**: unit test asserting a catalog's derived `theme` matches its
  linked `DesignSystem.tokens_css`/`colors` (AC-11).
- **Response shape regression**: existing OpenAI-compat response fixtures re-run to confirm no
  `a2ui` field appears for agents that never call the A2UI output path (AC-1).

## References

- [ADR-070426-3a1f: A2UI declarative agent-driven UI protocol adoption](../adr/ADR-070426-3a1f-a2ui-declarative-ui-protocol-adoption.md)
- [ADR-058: Agent-to-agent (A2A) delegation protocol](../adr/ADR-058-a2a-delegation-protocol.md)
- [ADR-083: Skills and MCP gateway trust](../adr/ADR-083-skills-mcp-trust.md)
- [ADR-061: maistro-design — composable design skills + design systems](../adr/ADR-061-maistro-design-package.md)
- [ADR-100: Bundled and cataloged Open Design design systems](../adr/ADR-100-bundled-open-design-systems.md)
- A2UI project: `/home/user/A2UI/docs/concepts/{data-flow,components,data-binding,actions,catalogs}.md`,
  `specification/v0_10/`, `agent_sdks/python/src/a2ui/`
- Seams: `packages/maistro-core/src/maistro/conduit.py`, `maistro.types.security.TrustTier`,
  `maistro.sessions`, `packages/maistro-design/src/maistro_design/types.py` (`DesignSystem`),
  `packages/maistro-design/src/maistro_design/scan.py` (`scan_design_system_content()` pattern)

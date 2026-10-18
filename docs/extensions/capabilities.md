# Capability examples

Every capability, effect, and data scope an extension may declare, with a
worked manifest fragment. The rule underneath all of them: **least authority
by default.** A capability is a claim a host must review and grant; the
reference extension declares none, and many honest extensions need none.

The vocabularies are closed and normative in the SDK package's schema
(M9-A1); this page shows how to use them.

## The baseline: nothing

The reference extension greets. It needs no data, no network, no filesystem,
no secrets — so it declares none, and a host grants none:

```json
{
  "family": "tool",
  "capabilities": [],
  "effects": ["read-only"],
  "data": { "scopes": [] }
}
```

Start here and add only what a missing capability makes impossible.

## `network.outbound` — calling an external API

A weather tool. Note the pairing: the capability comes with an allowlist and
a port pin, so the grant is a scope, not the open internet. Outbound HTTP
goes through the product's central seam (ADR-082326-5386):

```json
{
  "capabilities": ["network.outbound"],
  "effects": ["external-side-effect"],
  "network": { "allow": ["api.weather.example"], "allowed_ports": [443] }
}
```

## `workspace.read` — reading workspace data

A reporting tool that aggregates project scope data (ADR-081426-b1d3). The
scope is the *category*; row-level visibility is the host's grant decision:

```json
{
  "capabilities": ["workspace.read"],
  "effects": ["read-only"],
  "data": { "scopes": ["workspace"] }
}
```

## `memory.write` — a memory curation skill

Writes go through the memory layers (ADR-091) and are **mutating** — say so:

```json
{
  "capabilities": ["memory.read", "memory.write"],
  "effects": ["mutating"],
  "data": { "scopes": ["memory"] }
}
```

## `tool.invoke` — an orchestrating skill

Calling other tools through the governed surface (ADR-082226-4478). This is
the one capability that can compose others' authority, so expect the most
review:

```json
{
  "capabilities": ["tool.invoke", "workspace.read"],
  "effects": ["read-only"],
  "data": { "scopes": ["workspace", "run"] }
}
```

## `filesystem.read` / `filesystem.write` — sandboxed files

Filesystem authority is sandbox-scoped (ADR-093); declare the modes you need
and nothing more:

```json
{
  "capabilities": ["filesystem.read"],
  "effects": ["read-only"],
  "filesystem": { "mode": "read", "paths": ["exports/"] }
}
```

## `secrets.read` — named references, never values

A manifest names secret *references*; values stay with the host's secret
store, redaction posture applies (ADR-064):

```json
{
  "capabilities": ["secrets.read", "network.outbound"],
  "effects": ["external-side-effect"],
  "secrets": [{ "name": "WEATHER_API_KEY" }],
  "network": { "allow": ["api.weather.example"], "allowed_ports": [443] }
}
```

## Effects: say what your code *does*

Effects are the reversibility class (ADR-050) of what the extension does,
and reviewers read them as the promise:

| Effect | Promise | Typical |
|--------|---------|---------|
| `read-only` | nothing changes anywhere | report/greeter/inspector |
| `mutating` | changes host state, reversible | memory curation, drafting |
| `external-side-effect` | reaches outside the deployment | API callers, webhooks |
| `irreversible` | cannot be undone by the host | external writes of record |

An implementation that breaks its declared effect is a policy violation, not
a style issue: the effect declaration is what grant resolution and review
reason from.

## Choosing families

The `family` binds the extension to a lifecycle contract: `tool` (governed
tool surface), `skill` (skills marketplace), `mcp-gateway` (external MCP
servers), `capability-provider` (capability slots), `renderer-plugin`
(external renderers). Pick the one whose lifecycle you want; the
[manifest reference](manifest-reference.md) anchors each to its ADR.

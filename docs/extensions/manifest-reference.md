# Extension manifest reference

`extension.json` is the extension's authority *declaration*, not the grant:
it is what a host may consider granting (the runtime binds declarations to
grants — see [capabilities.md](capabilities.md)). It is data, validated
before any extension code runs.

The **normative schema is code**: the versioned extension SDK package
(`maistro-ext-sdk`, M9-A1, #949) ships the Pydantic model tree that defines
every field, its strictness (`extra="forbid"` everywhere — an unknown key or
a misspelled authority name is a validation error, never an ignored line),
and the closed vocabularies below. This page is the author-facing field
guide; when this page and the SDK disagree, the SDK wins and this page is the
bug.

## Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | `publisher.name`, both segments slug-cased (`[a-z0-9-]`). Namespaces every extension under its publisher. |
| `publisher` | string | yes | The publisher slug; must equal the `id` prefix. |
| `version` | string | yes | The extension's own `MAJOR.MINOR.PATCH` version. |
| `title` | string | yes | Human-readable name. |
| `description` | string | yes | One paragraph: what it does, what it touches. |
| `contract` | string | yes | The manifest-contract range this manifest codes against, e.g. `>=1.0.0,<2.0.0`. See [versioning](#contract-versioning-and-deprecation). |
| `family` | string | yes | One of the closed extension families (below). |
| `capabilities` | string[] | yes | Authority vocabulary names (below). Empty is valid and common. |
| `effects` | string[] | yes | Reversibility classes of what the extension does (below). |
| `data.scopes` | string[] | yes | Categories of product data touched (below). Coarse by design; row-level scope is the host's grant-time decision. |
| `network` | object | no | `allow` (host patterns) and `allowed_ports` for `network.outbound`. |
| `filesystem` | object | no | Sandbox filesystem authority for `filesystem.read`/`write`. |
| `secrets` | array | no | Named secret *references* (`[A-Z][A-Z0-9_]*` env-style names) for `secrets.read` — never values. |
| `dependencies` | array | no | Other extensions this one requires (`id` + version range). |
| `entrypoint` | object | yes | `module` (dotted import path, lexical only — never resolved during validation) and `object` (attribute name on that module). |

## Closed vocabularies

Closed on purpose: an unknown name fails validation rather than inventing
authority by misspelling.

**Extension families** — each binds to a lifecycle contract:

| Family | Contract anchor |
|--------|-----------------|
| `tool` | governed tool surface (ADR-082226-4478) |
| `skill` | skills marketplace (ADR-083 Part A) |
| `mcp-gateway` | external MCP servers (ADR-083 Part B) |
| `capability-provider` | capability slots/providers (SPEC-184, ADR-081226-6b46, ADR-070426-f2a0) |
| `renderer-plugin` | external renderers (ADR-070426-f2a0) |

**Capabilities** — `workspace.read`, `workspace.write`, `agent.read`,
`run.read`, `memory.read`, `memory.write`, `tool.invoke`,
`network.outbound`, `filesystem.read`, `filesystem.write`, `secrets.read`.
Anchors per name: workspace data (ADR-081426-b1d3), agent identity/spec
metadata, the read-only Run/NodeRun projection (extension code never writes
the execution model), memory layers (ADR-091), the governed tool surface
(ADR-082226-4478), outbound HTTP via the central seam (ADR-082326-5386), the
sandboxed filesystem (ADR-093), and named secret references (ADR-064
redaction posture).

**Effects** (ADR-050 taxonomy) — `read-only`, `mutating`,
`external-side-effect`, `irreversible`.

**Data scopes** — `workspace`, `agent`, `run`, `memory`, `messages`,
`artifacts`.

**Optional features** a host may enable but a manifest need not declare —
`streaming`, `background`, `scheduled`, `interactive`.

## Contract versioning and deprecation

Public API changes require explicit contract-version/deprecation handling —
this is enforced structure, not advice:

- **The contract version is the version of the manifest schema** — fields,
  authority vocabulary, validation behavior. It versions independently of the
  application and of any package's release version. A host that rejects a
  manifest names the contract version it enforces, so an author can tell
  "malformed manifest" from "manifest predates this host".
- **Breaking changes bump the contract major.** Adding a field with a default
  is a minor change; removing or redefining one, or changing what an existing
  authority name means, is a major bump — and a major bump lands behind a
  supported-majors gate, never as a silent reinterpretation of old documents.
- **Pin exactly the major you code against.** `>=1.0.0,<2.0.0` — a range
  spanning two majors claims compatibility with a schema that does not exist
  yet.
- **Deprecations are announced in a minor** — the field or name keeps
  validating, the SDK documents its replacement, and the next major removes
  it. An extension that still declares a deprecated name validates until the
  major boundary it already pinned as its ceiling.
- Changes to product-private internals never require a contract bump (or any
  extension change at all) — only the public contract surfaces here.

The reference extension pins `>=1.0.0,<2.0.0`; its own tests assert the range
pins exactly one major.

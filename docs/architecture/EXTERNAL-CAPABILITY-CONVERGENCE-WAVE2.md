# External capability convergence, wave 2: protocol seams and new evidence

**Status:** research and review, not an approved adoption ADR.  
**Date:** 2026-11-22. **Base inspected:** develop via GitHub file reads/search.  
**Companion:** [first-wave matrix](EXTERNAL-CAPABILITY-CONVERGENCE-AUDIT.md), [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md), [ADR-039](../adr/ADR-039-external-library-adoption-policy.md).  
**Code changes:** none. **Tests executed:** none. A negative code-search result is not proof of system-wide absence.

## Key corrections to the first wave

1. **There is a demonstrable Agent Skills interoperability mismatch.** The internal SKILL.md parser accepts host-specific snake_case names and requires a parameters mapping; the upstream Agent Skills spec accepts hyphen-separated names and requires only name + description in a directory named after the skill. SPEC-208's advertised import/export portability is narrower than upstream standards compatibility. Tracked by [#2499](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2499).
2. **The project already has substantial adversarial durability testing.** [Failpoint matrix #883](../testing/failpoint-matrix-evidence.md) covers 22 cells and explicitly demonstrates ordinary work-after-external-effect can double-apply a modeled effect upon retry, while the governed Invocation boundary prevents that at its tested seams. This is a known *layering contract*, not a newly confirmed production defect. The correct action is audit of *all reachable effect-producing consumers*, plus broader cross-process and Postgres tests, not claiming no recovery work exists.
3. **SLSA/Cosign adoption is already present in release tooling.** [Release workflow](../../.github/workflows/release.yml) pins Syft/Cosign and [check-image-pins.py](../../scripts/check-image-pins.py) verifies SLSA attestation base digests. No new attestation engine should be proposed until **real run evidence**, subject coverage and consumer-side verification are assessed.
4. **MCP Apps is not A2UI.** A2UI describes declarative, catalog-validated components. MCP Apps safely embeds *HTML/JavaScript applications* supplied by external MCP tools. The #967 extension manifest rejects arbitrary scripts/iframes in declarative component content; we must not pretend an MCP App can ride that same renderer unchanged. Reuse its governance policy/provenance where appropriate while defining a separate sandboxed-host presentation type.

## Architecture protocol map

| Boundary | Protocol | Wire/payload authority | Do not duplicate |
| --- | --- | --- | --- |
| mAIstro runtime → application frontend | [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | Live agent events and frontend interaction; projection of canonical EventStore | Run authority, event sequence, HITL ledger |
| Agent → declarative component tree | [A2UI](https://github.com/google/A2UI) | Component and data-model messages bounded by catalog | UI registry or canonical Workspace state |
| External MCP tool → embedded host application | [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) | UI resource, iframe sandbox, app ↔ host RPC | Tool grants, network permissions, Workspace permissions |
| Coding agent ↔ IDE/editor | [ACP](https://github.com/agentclientprotocol/agent-client-protocol) | JSON-RPC sessions, progress, plans, permissions | Harness lifecycle ownership or canonical Attempts |
| Async MCP tool request ↔ MCP client | [MCP Tasks extension](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks) | Protocol-visible async task lifecycle; version/capability negotiated | Canonical Run/Task/HITL authority |
| External agent ↔ external agent | [A2A](https://a2a-protocol.org/latest/) | Remote task/delegation messages | Graph delegation budget/authorization |
| Agent capability package ↔ consumers | [Agent Skills](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx) | Portable SKILL.md directory bundle | Host tool authorization and trust assignment |
| Agent/Graph definition ↔ other frameworks | [Oracle Agent Spec](https://github.com/oracle/agent-spec) | Static import/export grammar | Live Run and governance identity |

### Avoid the “one protocol for everything” error

These protocols are **not** substitutes for one another. Build a small adapter per externally useful boundary. For example, an ACP coding-agent provider should project its progress into the existing canonical observations, which the AG-UI frontend may later display; it should *not* inject raw ACP events as canonical events. An MCP App host renders server-supplied HTML under iframe isolation, not as an A2UI declarative component.

## Second-wave candidate matrix

| Priority | External candidate | Existing contract / code observed | Gap and confidence | Disposition |
| --- | --- | --- | --- | --- |
| **P1** | **MCP Apps (SEP-1865, stable 2026-01-26)** | [MCP routes](../../packages/hive-conductor/backend/routes/mcp.py), [#967 UI extension](../../packages/maistro-core/src/maistro/extensions/ui.py), [SPEC-277](../specs/SPEC-277-a2ui-surface-integration.md) | No exact ui:// or text/html;profile=mcp-app hit in targeted source search. Positive supported use case unverified. Need trusted sandboxed HTML host and tool/resource capability negotiation if intended. | **TRIAL** host extension, *not* A2UI reimplementation; no production dependency without consumer. |
| **P1** | **ACP (Agent Client Protocol, Zed/JetBrains)** | [ADR-101](../adr/ADR-101-foreign-harness-adapters-and-portability.md), [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md), [Harness matrix](../security/HARNESS-SUPPORT-MATRIX.md) | Preferred Codex App Server and OpenCode adapters already exist. No exact agentclientprotocol/session-prompt matches. ACP enables portable IDE-facing agent integration and could normalize multiple providers, but is not an independent scheduler. | **COMPAT** provider adapter pilot; version-pin official schema; follow existing preferred provider order. |
| **P1** | **MCP Tasks extension and elicitation** | [MCP routes](../../packages/hive-conductor/backend/routes/mcp.py), [canonical HITL](../research/909-human-agent-interaction-generative-ui-mixed-initiative.md), [Event/Checkpoint](../specs/SPEC-081226-7248-event-checkpoint-model.md) | No exact io.modelcontextprotocol/tasks, tasks/get, or elicitation/create matches. Explicit capability negotiation and old/new Tasks lifecycle incompatibility require testing. | **COMPAT** at existing MCP gateway if long-running MCP tools are required; never launch another Task truth store. |
| **P1** | **Agent Skills conformance and reference validator** | [parser](../../packages/maistro-core/src/maistro/skills/parser.py), [loader](../../packages/maistro-core/src/maistro/skills/loader.py), [importer](../../packages/maistro-core/src/maistro/portability/skills.py), [exporter](../../packages/maistro-core/src/maistro/portability/export.py) | **Code-confirmed incompatibility** with upstream legal SKILL.md bundles, distinct from unsupported-tool execution. | **FIX COMPATIBILITY** behind new importer/exporter while preserving legacy forms. [Issue #2499](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2499). |
| **P0 research** | **Restate 1.7 durable virtual objects / flow control** | [execution](../../packages/maistro-core/src/maistro/runs/execution.py), [fencing](../../packages/maistro-core/src/maistro/sandbox/fence.py), [consumer cursor](../../packages/maistro-core/src/maistro/events/consumer_cursor.py), [failpoints](../testing/failpoint-matrix-evidence.md) | No justified claim that mAIstro is missing durable retries/fencing. Restate provides a useful independent *model* for per-key serialization, idempotency, backpressure, durable RPC and waiting interactions. | **DIFFERENTIAL TESTS**, not import as core; promote implementation only on measured failure. |
| **P2** | **OpenFeature 0.9 feature flag evaluation** | [ADR-078 config ownership](../adr/ADR-078-configuration-management.md), [SPEC-062226-fb23](../specs/SPEC-062226-fb23-config-store-db-cli-api.md) | ADR-078 explicitly names DB-owned feature flags. Search for DbConfigStore/config_entries returned only the spec; true runtime coverage needs entrypoint inspection. OpenFeature could standardize evaluation semantics but must not own flag state or policy. | **DEFER/ADAPT** at evaluation API once canonical hot-config is reachable. |
| **P2** | **Cedar / SpiceDB authorization models** | [Workspace cutover P0.1–P0.2](WORKSPACE-CUTOVER-PLAN.md), [governed actions](../../packages/maistro-core/src/maistro/extensions/ui.py) | Authorization is already canonical and default-deny intended. Cedar (principal/action/resource/context) and SpiceDB (relationship checks) can serve as *independent reference models* to test complex Workspace sharing rather than introduce another policy database. | **EVALUATE AS TEST ORACLES**, no production policy authority change. |
| **P2** | **in-toto / SLSA / Sigstore provenance** | [release.yml](../../.github/workflows/release.yml), [image pin attestation checker](../../scripts/check-image-pins.py), [ADR-039](../adr/ADR-039-external-library-adoption-policy.md) | **Already implemented in release path** by source inspection; no evidence here of a successful published release run or verification consumer. | **VERIFY EXISTING** attestation producer/consumer coverage, do not import another attestation system. |

## Acceptance-based engineering spikes

### A. MCP Apps, tool-to-host UI (P1, non-blocking unless a consumer is approved)

- Use the pinned 2026-01-26 specification and official SDK reference only.
- Offer a single explicitly allowlisted UI resource returned from one **trusted, authorized** MCP server. Negotiate the io.modelcontextprotocol/ui extension; refuse unadvertised capabilities.
- Host the returned HTML in a separate sandboxed origin/frame; start with no egress. Apply declared CSP, network and navigation permissions; no parent DOM or local credential exposure.
- All app-initiated tool calls traverse the same MCP gateway, effective principal, Warden/Sentinel and governed Invocation controls.
- App reload, forged messages, stale grants, disabled extension and two-Workspace attempted cross-read have tests.
- **Decision:** if no real user-facing embedded MCP tool use case, **defer**. Do not replace A2UI or weaken #967 to permit arbitrary scripts.

### B. ACP coding-agent harness (P1)

- Pin one released ACP schema; distinguish v1 and v2 draft evolution explicitly. Verify tested editor/agent versions.
- Implement a HarnessRunner adapter: initialize/auth, create session, turn/prompt, progress stream, cancel and resumption *as supported by the chosen version*; foreign session IDs are provider metadata.
- Requests for filesystem edits, terminal commands and permissions must go through mAIstro's sandbox and Binding/Invocation or canonical HITL. Do not let an ACP agent act as an independent workspace principal.
- Differential test against existing Codex App Server provider: token streaming fidelity, tool/cancel semantics, crash/restart, workdir isolation, revoked grant and duplicate notifications.
- Do **not** replace Codex App Server as the preferred Codex provider without comparative evidence.

### C. MCP Tasks extension (P1)

- Record protocol version and negotiated task extension; the 2025-11-25 experimental Tasks lifecycle differs from the newer extension.
- Map MCP task ID to canonical Run/Invocation ID with a durable lookup/projection, not a second task table/state machine.
- Test working/input-required/completed/failed/cancelled statuses with correct non-terminal vs terminal mapping; unknown statuses must fail safely.
- Reconnect to async tool task without re-dispatching a previously admitted irreversible invocation. Auth and Workspace membership must be rechecked.
- An MCP server asking for input creates a *canonical* HITL pause; its response can settle only through governed server routes.
- If no MCP tool actually needs async tasks, defer wire support.

### D. Agent Skills conformance (P1, verified mismatch)

- Upstream reference fixtures are executable acceptance criteria: a standard hyphenated name and no parameters imports successfully, folder matches skill name, and an export passes skills-ref validation.
- Preserve legacy snake_case + parameters support. Treat public skill name and internal tool handle as different namespaces if needed; never silently rename a collision.
- Security scan scripts/assets as inert data; no implicit execution or auto-approval from a SKILL.md allowed-tools field.
- The exact issue contains positive, negative, legacy and authority-specific ACs: [#2499](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2499).

### E. Durable effects: reachability and differential failure matrix (P0 investigation)

- **Already done:** [#883 failpoint lab](../testing/failpoint-matrix-evidence.md) documents a governed Invocation ledger that prevents effect duplication under its tested crash windows. The same document deliberately allows **ordinary work** to rerun.
- **Missing evidence to seek:** list every reachable execution path calling a network client, filesystem destructive operation, git push/merge, credential write, tool dispatcher or external provider without a governed Invocation. Classify read-only, idempotent, compensatable or irreversible by *actual effect*, not node label.
- For every irreversible path, demonstrate that the provider dispatch cannot be retried without a stable logical effect key and an evidence reconciliation gate; test crash after remote effect but before canonical commit, stale fence and two competing workers.
- Compare to Restate's virtual objects/per-key serialization, DBOS step journal and Temporal Activity retry classes. Reuse native stores; only open a **new M1 defect** on a reachable ungoverned path with reproducible evidence.

### F. OpenFeature, policy models and attestation (P2/verify)

- For OpenFeature, show a real flag consumer, DB-owned ConfigStore runtime and cross-replica invalidation before adding an evaluation adapter; never make flag service a second config store.
- For Cedar/SpiceDB, generate a fixed authorization case set from canonical principal/membership/scope/role semantics; compare correct permit/deny results to the external reference without persisting external relationships as truth. Particularly cover revocation after read, Workspace transfer, shared topics and cross-scope delegated agents.
- For SLSA, inspect actual GitHub Actions run output, publication artifact hashes, authenticated provenance claims, pinned bases and consumer-side verification. The presence of checks in YAML is not equivalent to a published proof.

## Milestone boundaries and decisions

| Outcome | Can affect M1? | Reason |
| --- | --- | --- |
| Reachable irreversible effect bypassing governed Invocation | **Yes, if proven** | Native safety/correctness invariant, not an interoperability enhancement |
| AG-UI / A2UI / MCP Apps new frontend support | **Not by default** | Requires cutover P0.3 / host-specific consumers, should be M3+/interaction owners |
| ACP coding harness | No by default | SPEC-208 / ADR-101 portability and provider work |
| Agent Skills conformance | No by default | #2499 resolves a concrete portability compatibility contract |
| MCP Tasks extension | No by default | Tool boundary compatibility, only when real async MCP consumers need it |
| Restate/Temporal/DBOS patterns | **Tests can run now** | No new runtime; route proven defects to existing M1 owners |
| OpenFeature, Cedar/SpiceDB or attestation changes | No by default | Maturity/interop test exploration or verification of existing gates |

## Sources and specific version warnings

- [MCP Apps stable 2026-01-26 extension](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx), [host SDK](https://github.com/modelcontextprotocol/ext-apps).
- [Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol), [ACP v1 overview](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/overview.mdx), [ACP v2 overview](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v2/overview.mdx). Do not assume all features are present in the pinned release.
- [MCP 2026-07-28 release candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) and [MCP Tasks extension](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks). Experimental 2025-11 Tasks are **not** wire-equivalent to the newer extension.
- [Agent Skills specification and directory format](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx).
- [Restate 1.7 virtual queues/flow control](https://restate.dev/blog/announcing-restate-1-7), [OpenFeature 0.9 announcement](https://openfeature.dev/blog/openfeature-mid-2026-update/).
- [Cedar authorization](https://docs.cedarpolicy.com/auth/authorization.html), [SpiceDB ReBAC model](https://authzed.com/docs/spicedb/getting-started/faq), [in-toto](https://in-toto.io/docs/specs/).

**Review request:** Prioritize the code-confirmed Agent Skills divergence; decide whether MCP Apps and ACP have real mAIstro consumers; treat ungoverned-effect reachability as the correctness-critical audit. No new runtime imports or authority changes are requested.

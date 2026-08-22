---
id: ADR-082226-4478
title: "Retire single-purpose demo endpoints in favour of one governed tool surface"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-22
substrate:
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-083
  - maistro-engine#ADR-096
implements: []
related:
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-062
  - maistro-engine#ADR-073
  - maistro-engine#ADR-082226-5104
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082226-4478: Retire single-purpose demo endpoints in favour of one governed tool surface

## Context

A PM demo left the Conductor with a set of endpoints that each do one integration by
hand. Auditing the unreachable-module ledger (#33) surfaced how far that pattern spread.

**Tool execution happens in at least four unrelated places, none of them the canonical one:**

| Where | How it dispatches | Covers |
|---|---|---|
| `routes/pm_fleet_v2.py::POST /v1/pm-fleet/tools/execute` | `if req.tool.startswith("github_") … elif "gitlab_"`, else `{"error": …}` | two vendors, hard-coded |
| `services/tool_executor.py` | a different hard-coded set | `web_search`, `browse_url`, `clarify` |
| `routes/daily_report_v2.py` | raw `httpx` per vendor | Jira, Airtable |
| `routes/mcp.py` | — | registers, scans and discovers MCP tools, but **has no execute endpoint** |

Meanwhile `maistro.capabilities` already implements the accepted
`Capability → Provider → Binding → Invocation` path (ADR-081226-6b46) with an approval store,
an invocation store and a governed-invocation seam, and `maistro.graph.nodes` registers
`jira.poll`, `airtable.poll` and their siblings as node kinds. Neither is reached by any of the
four paths above.

So the generalised surface is *half-built and unrouted*, while the demo surface is *live and
duplicated per vendor*. Adding the next integration under the current shape means a fifth
bespoke client, or a new `elif` on a string prefix.

Two of these have already been removed as unreachable: `routes/chat_complete.py` and
`routes/daily_report.py` (commit 490f5fa). The rest are live and need a replacement before they
can go.

## Decision

**One governed tool surface. No per-integration endpoints.**

1. **Tools are discovered, not enumerated in code.** MCP servers and registered node kinds are
   the two sources. `routes/mcp.py` already discovers; what it lacks is execution.

2. **Execution goes through `Capability → Provider → Binding → Invocation`.** Every tool call
   produces an `Invocation` record carrying its authorization decision, its provider, and its
   cost — which is what ADR-081226-6b46 already decided and what #55, #56 and #57 implement.
   Prefix-string dispatch (`tool.startswith("github_")`) is not a routing strategy; it is an
   `elif` chain that fails open on an unknown name.

3. **Single-purpose endpoints retire onto it.** `/v1/pm-fleet/tools/execute`,
   `/v1/daily-report`, and the remaining PM-demo routes are demo artefacts. Each retires when
   the general path can serve its use case — not before, because two of them back live UI.

4. **A retirement removes the whole feature, not just the backend.** `/v1/daily-report` is
   called by `frontend/src/components/DailyReport.tsx` and asserted by
   `tests/e2e/test_pm_workflow_api.py`. Deleting the route alone would leave a blank panel and
   a red suite; the route, its component and its test go together, or the endpoint is rebuilt
   on the general surface. Which of those applies is a product call per feature.

5. **`security.dangerous_tools` and the ADR-050/051 reversibility and approval gates apply at
   the one seam.** That is the point of having one: today a tool executed through
   `pm_fleet_v2` passes no gate that a tool executed through `tool_executor` does, and neither
   consults the `ReversibilityRegistry` — a gap `SECURITY.md` already records.

## Consequences

### Positive

- Adding an integration stops meaning "add an endpoint". It means registering an MCP server or
  a node kind, which is configuration rather than code.
- Every tool effect becomes auditable at one seam, which is what makes ADR-073's Sentinel
  enforcement and ADR-050/051's approval gates reachable at all.
- The four duplicate dispatch paths collapse, and with them the class of bug where a tool is
  governed on one path and ungoverned on another.
- `routes/mcp.py` stops being a registry that cannot run anything.

### Negative / Trade-offs

- Live surface is involved. `/v1/daily-report` and `/v1/pm-fleet/*` back real UI, so this is a
  migration with parity work, not a sweep — and #35's rule applies.
- A general surface is slower to use for the first integration than a bespoke endpoint. That
  cost is real and is paid once; the current shape pays it every time instead.
- MCP tool discovery introduces a supply-chain surface that ADR-083 and #59 must govern before
  arbitrary servers can be registered.

### Neutral

- This does not decide whether the Daily Report *feature* is worth keeping. It decides that if
  it is kept, it is served by the general surface.
- `maistro.capabilities` is already unreachable in places (2 of 31 modules); connecting it is
  #55, and this ADR is a consumer of that work rather than a duplicate of it.

## Open questions

1. **Which demo features survive at all?** Daily Report, PM Fleet and topK testing each need a
   keep-or-drop call before their retirement path matters.
2. **MCP or node kinds for a given integration?** Jira has both today —
   `maistro.tools.atlassian`'s MCP client and the `jira.poll` node kind. One should be the
   default and the other the exception.
3. **Where does the general execute endpoint live?** `/v1/mcp/tools/{name}/execute` keeps it
   beside discovery; a neutral `/v1/tools/execute` does not imply MCP is the only source.
4. **Does the frontend call tools directly**, or only through chat and DAG runs? That decides
   whether an HTTP execute endpoint is needed at all, or whether the seam is internal.

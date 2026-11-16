# Terminology

Product-facing terms on the left, internal/technical terms on the right.
External docs, UI, and user-facing APIs use product terms. Internal code comments
and architecture docs may use either.

**v1.0 product:** **Workspaces** replaces the legacy Conductor page tree. Cutover:
[WORKSPACE-CUTOVER-PLAN.md](../architecture/WORKSPACE-CUTOVER-PLAN.md). Release contract:
[ROADMAP.md](../../ROADMAP.md).

## Product ↔ Internal mapping

| Product term | Internal term | Notes |
|--------------|---------------|-------|
| **Workspace** | Workspace | Scoped product context (goals, backlog, agent, memory) |
| **Workspaces** (product) | `packages/hive-conductor` | v1.0 default UI; replaces legacy Conductor routes |
| **Workflow** | DAG | A directed acyclic graph of steps |
| **Step** | Node | A single unit of work in a workflow |
| **Transition** / Dependency | Edge | Connection between steps |
| **Worker** | Agent | An autonomous executor with a role |
| **Skill** | Capability / Tool | Something a worker can do |
| **Workflow Run** | DAG Run | A single execution of a workflow |
| **Hive Conductor** | — | Internal name for the UI/BFF layer (legacy label; package `hive-conductor`) |
| **Hive Swarm** | — | The collective of workers executing workflows |

## Package names

| Package | Role |
|---------|------|
| `maistro-core` | Shared substrate: graph, memory, security, types |
| `maistro-server` | Control plane / production execution engine |
| `maistro-sandbox-worker` | **Planned, not built (#81).** A separate service owning a KVM or gVisor runtime, which is what a Tier-1 or Tier-2 backend would need. Today isolation is in-process via `maistro.sandbox`; there is no such package and no such compose service. |
| `maistro-evolve` | Self-improvement / benchmark evaluation |
| `maistro-canvas` | Image generation pipeline |
| `hive-conductor` | UI + BFF (not an execution engine in production) |

## Naming rules

1. **User-facing surfaces** (UI labels, API response fields, CLI output, docs for
   users) use product terms: Workflow, Step, Worker, Skill.
2. **Internal code** may use DAG/node/edge/agent — but new public APIs prefer
   product terms.
3. **Never mix** in a single user-facing context: don't say "this DAG has 3 Steps"
   or "the Workflow's nodes." Pick one vocabulary per surface.
4. **Workspaces** is the user-facing product name for v1.0. **Hive Conductor** is the
   historical/internal label for the same UI/BFF package (`hive-conductor`).
5. The UI/BFF does not execute work in production — `maistro-server` and the canonical
   Run spine do. The UI conducts the *user experience* of managing the swarm.

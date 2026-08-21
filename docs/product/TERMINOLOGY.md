# Terminology

Product-facing terms on the left, internal/technical terms on the right.
External docs, UI, and user-facing APIs use product terms. Internal code comments
and architecture docs may use either.

## Product ↔ Internal mapping

| Product term | Internal term | Notes |
|--------------|---------------|-------|
| **Workflow** | DAG | A directed acyclic graph of steps |
| **Step** | Node | A single unit of work in a workflow |
| **Transition** / Dependency | Edge | Connection between steps |
| **Worker** | Agent | An autonomous executor with a role |
| **Skill** | Capability / Tool | Something a worker can do |
| **Workflow Run** | DAG Run | A single execution of a workflow |
| **Hive Conductor** | — | The UI/BFF layer (dashboard + chat) |
| **Hive Swarm** | — | The collective of workers executing workflows |

## Package names

| Package | Role |
|---------|------|
| `maistro-core` | Shared substrate: graph, memory, security, types |
| `maistro-server` | Control plane / production execution engine |
| `maistro-sandbox-worker` | Isolated execution environment (owns KVM/container runtime) |
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
4. **Hive Conductor** is always the UI layer. It does not "conduct" execution in
   production — it conducts the *user experience* of managing the swarm.

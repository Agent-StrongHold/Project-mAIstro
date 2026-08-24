---
id: ADR-082426-2192
title: "maistro-server builds a Container, and the OpenAI door routes through it"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-24
substrate:
  - maistro-engine#ADR-082326-c126
implements: []
related:
  - maistro-engine#ADR-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-2192: maistro-server builds a Container, and the OpenAI door routes through it

## Context

`maistro-server`'s OpenAI-compatible endpoint calls `maistro.agents.conductor.run_task`
directly. `run_task` is the executor the `TaskRunner` invokes — not an entry point — so the
endpoint skips the classifier, the intent registry, the router and the session store. #150
closed the two gaps that could be closed without a Container: the turn is Gate-scanned, and it
gets a canonical Run. What is left is the routing itself, and #142 names the blocker precisely:

> The server has no DI container today (`main.py` reads `DATABASE_URL` directly and wires the
> spine by hand). Decide whether the endpoint builds a `Container` at startup or the conduit
> pipeline is reachable some lighter way — that decision is the substance of this issue and
> should be recorded.

Three facts constrain the answer.

**The Conduit is not reachable without a Container.** `Conduit.route_request` reads
`container.gate`, `container.classifier`, `container.config.task_types`,
`container.intent_registry` and `container.agents`. There is no lighter object that carries
those; a "conduit-lite" would be a second wiring of the same five things, which is the defect
this issue exists to remove, one layer down.

**A second Container would mean a second execution spine.** `create_container` wires
`wire_execution_spine` and `wire_chat_admission` itself. `main.py` calls both by hand today and
hands the pieces to the task queue, `runs.configure_run_store` and the chat endpoint. Building a
Container *beside* that gives the process two `RunStore`s: a `run_id` returned by `POST /tasks`
would not resolve for a chat turn and vice versa — an advertised handle that silently stops
resolving, which is the failure #132 called out by name.

**`Conduit.route_request` answers "No agents available." with an empty roster.** The server has
never built agents; `settings.agents_dir` defaults to `""`. `run_task` does not need a roster —
it selects a tier, resolves a model and calls the gateway — so the endpoint works today on a
deployment that has configured no agents at all. Routing naively through the Conduit would turn
every one of those deployments' chat turns into a refusal.

## Decision

**1. The server builds one `Container` during lifespan, and the spine comes from it.**

`main.py` maps its `Settings` to an `AgentConfig` and calls `create_container(config,
pg_pool=spine_pool)`, passing the pool it already opened so the process holds one pool and one
spine. `container.run_store`, `container.task_admitter` and `container.chat_admitter` then feed
the task queue, `runs.configure_run_store` and the chat endpoint, replacing the by-hand
`wire_execution_spine` call. One Container, one spine, one `run_id` namespace.

The Container is required, not best-effort. A server that failed to build one and fell back to
`run_task` would be the two-doors defect again, chosen at runtime and invisible in the logs of
the deployment it happened to. `create_container` refuses an empty `router_api_key`, so the
server states that requirement in its own `_validate_startup` — beside the two checks already
there, with a message naming the variable — rather than letting a `ConfigError` surface from
inside container wiring at lifespan time.

**2. The roster falls back to the conductor, rather than to nothing.**

The Container's `agents` map is populated from `agents_dir` when the deployment names one. When
it does not, the server registers a single agent that executes through `run_task` — the same
executor the endpoint calls today, reached through the Conduit instead of around it.

This is what makes the change safe to ship: a deployment with no roster keeps exactly the
behaviour it has, and gains the Gate, the classifier, the router and the session store on the
way in. The classifier's `task_type` is not decoration on that path either — it selects the tier
`run_task` runs at, which was previously always the default.

The alternative — requiring `agents_dir` — was rejected. It converts a working endpoint into a
refusal for every deployment that has not configured a roster, in service of an internal
convergence those deployments did not ask for.

**3. The endpoint delegates the whole turn to `Container.route_request`.**

The scan, the Run admission and the terminalization `chat_completions.py` grew in #150 exist
because there was no Container to do them. `Container.route_request` does all three, in the same
order and with the same rules — a turn is refused without a scan, and answered without a Run.
The endpoint keeps only what is genuinely its own: the OpenAI request and response shapes, the
SSE framing, the `X-Maistro-Run-Id` header, the abandoned-stream cleanup, and the 502/504
sanitisation that keeps upstream detail out of client-visible errors.

## Consequences

### Positive

- The OpenAI door stops being a second entry point. Every ordinary chat turn in the process now
  reaches the same seam, so a change to classification, routing or session handling lands on all
  of them at once instead of on whichever ones were remembered.
- One `RunStore` in the process. A `run_id` from any door resolves at `/runs/{run_id}`.
- The duplication #150 was forced into — a second Gate, a second admit/close pair — is deleted
  rather than maintained in parallel with the Container's.
- Chat turns get session history for the first time on this endpoint.

### Negative / Trade-offs

- **A deployment without `ROUTER_API_KEY` no longer starts.** It is a presence check rather than
  a functional dependency — nothing consumes the value — but it is `create_container`'s existing
  contract, which `hive-conductor` already lives with, and honouring it in one place is better
  than two packages disagreeing about whether a Container needs one.
- Startup does more work and can now fail for more reasons. That is the point of a fail-fast
  check, but it moves failures that used to appear on the first chat request to boot.
- The conductor-backed fallback agent is a real object with a real lifetime, not a shim that goes
  away on its own. It should be retired when a deployment can be expected to have a roster, and
  that expectation does not exist yet.

### Neutral

- Streaming is unchanged in shape. The endpoint has always computed the whole answer and then
  chunked it; routing through the Conduit does not make it token-streaming, and does not stop it
  from becoming so later.
- `POST /tasks` is untouched. It already went through the admitter and the queue; it now reads
  those off the Container instead of off a local variable.

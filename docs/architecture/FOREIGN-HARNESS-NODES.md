# Foreign harnesses as governed graph nodes (M1-D, issue #1613)

**Wrap, don't clone.** maistro is better than Pi and OpenClaw not by cloning
their channel UX, but by *hosting* them: a foreign harness — an OpenClaw
gateway agent, a Pi coding session, a Claude Code or equivalent CLI harness, a
LangGraph graph, another Conductor — is **one graph node** under the canonical
execution model `Goal -> Graph -> Run -> NodeRun -> Attempt`, with the same
envelope, the same audit, and the same `Capability -> Binding -> Invocation`
path as every native provider. Channels stay the harness's; governance stays
mAIstro's.

## The rules

1. **Provider, never a side door.** A harness adapter implements
   `HarnessRunner` (`maistro.capabilities.slots.harness_runner`) under the
   `harness_runner` capability slot (SAFE_NOOP), or dispatches as a
   `graph.harness.HarnessAdapter` through the `agent.spawn_harness` node. There
   is no raw HTTP/CLI path to a harness from product code — CI enforces this
   (`scripts/check-foreign-harness-egress.py`, the
   "foreign-harness egress" step in `.github/workflows/quality.yml`).
2. **One Invocation per dispatch.** The governed Invocation row records the
   harness id, the session/workspace hint, and the result payload, tied to the
   parent Run's `run_id` / `node_run_id` / `attempt_id` — the harness never
   gets its own execution identity (`maistro.graph.harness_targets` states this
   too: "physical work stays on Graph -> Run -> NodeRun -> Attempt").
3. **No credentials ride on requests.** Harness credentials are operator-wired
   through the sandbox's trusted env, mirroring Binding policy; no silent
   credential copy into the foreign process.
4. **Terminal states terminalize.** Failure, timeout, and cancel raise or
   settle through the bounded turn's `finally` (session stopped), the node
   fails or pauses honestly, and the Attempt terminalizes — an orphan claw
   session is never recorded as canonical success.
5. **Adding a harness is a Provider + Binding, not a product.** Concretely:
   subclass `SubprocessHarnessRunner` and override `build_command` (see
   `capabilities/providers/openclaw.py` and `capabilities/providers/pi.py`),
   register/activate in the capability registry, authorize a workspace-scoped
   Binding, and dispatch through `agent.spawn_harness`.

## Shipped adapters

| Harness | Provider | Minimum proof |
|---|---|---|
| OpenClaw | `OpenClawHarnessRunner` (`openclaw agent --message …` one outbound gateway task in a sandbox) | Invocation row carries harness id + session/workspace + result |
| Pi | `PiHarnessRunner` (`pi -p …` one print-mode coding-agent turn in a sandbox) | same |
| opencode | `OpencodeHarnessRunner` (SPEC-208) | same |
| Generic CLI | `SubprocessHarnessRunner` | same |

Fixtures may fake the far side (the sandbox seam); the near side is always the
real Invocation seam — see
`packages/maistro-core/tests/graph/nodes/test_foreign_harness_invocation.py`
for the OpenClaw/Pi-through-Invocation and one-parent-Run proofs.

## Deliberate non-goals

- **No WhatsApp/Telegram admission** — channels belong to the harness.
- **No vendoring OpenClaw or Pi** — the adapters drive their published CLI/API.
- **Pi is not the execution runtime** — it is one governed node among others;
  `Goal -> Graph -> Run -> NodeRun -> Attempt` remains the only scheduler.

## Related

- [ADR-101](../adr/ADR-101-foreign-harness-adapters-and-portability.md) —
  foreign harness adapters and portability
- [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md) — the
  `harness_runner` slot, safety wrapper, and adapter catalog
- [ADR-062](../adr/ADR-062-graph-execution-protocol.md) — graph execution

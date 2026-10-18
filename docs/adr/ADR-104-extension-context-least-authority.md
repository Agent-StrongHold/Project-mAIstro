---
id: ADR-104
title: "Canonical extension context and lifecycle: least-authority seams over the governed effect plane"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-05
accepted: 2026-10-05
substrate:
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#ADR-031
  - maistro-engine#SPEC-177
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/extensions/test_extension_contract_conformance.py
  - packages/maistro-core/tests/extensions/test_extension_reference_execution.py
ac-modules:
  AC-1: maistro.extensions.context
  AC-2: maistro.extensions.lifecycle
  AC-3: maistro.extensions.host
  AC-4: maistro.extensions.host
  AC-5: maistro.extensions
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Accepted
    date: 2026-10-05
---

# ADR-104: Canonical extension context and lifecycle — least-authority seams over the governed effect plane

Implements #950 under epic #938; builds toward #949 (SDK package/manifest)
and #951 (import enforcement).

## Context

Milestone M9 (#937) makes the platform governed-extensible: external developers
author extensions against a public SDK without importing product-private
internals (#938). Issue #950 owns the runtime-facing half of that contract —
the context and lifecycle interfaces through which extension code actually
executes — under a hard constraint the epic states as acceptance: *extension
code cannot receive undeclared authority merely by importing SDK objects*, and
*the context contains no unrestricted DB/store/container handles*.

The substrate already owns every authority the extension must never bypass:
the governed effect chain `Capability → Provider → Binding → Invocation`, the
execution chain `Graph → Run → NodeRun → Attempt`, the canonical
`Run/NodeRun/Attempt` cancellation fence, and the canonical event envelope
with its typed `provenance` field. The defect to avoid is a parallel extension
authority — a context that hands out a container, a second dispatch path, or
an ambient "current extension" global.

SPEC-177 (hyperagent graph execution) names that execution chain and is
cited as `related` rather than `substrate`: its acceptance criteria are
defined but the spec is not yet accepted, and a governing citation from an
active document must resolve to live authority (#374). This ADR claims no
authority over execution semantics it does not own; the citation becomes
governing when SPEC-177's own acceptance ladder accepts the spec.

## Decision

**1. One context object per invocation; it is the complete authority surface.**
`maistro.extensions.ExtensionContext` is the only object an extension receives
from the runtime. Its public surface is closed and pinned by conformance test:
`descriptor`, `identity`, `scope`, `config`, `cancellation`, `progress`,
`service()`, `invoke_effect()`, `report_progress()`. It is a `__slots__`
object with no `__dict__`, so later code cannot smuggle a handle onto it, and
it carries no store, session, container, or provider reference.

**2. Authority is declared, then granted; both halves are required.** The
`ExtensionDescriptor` records the extension's declared ceiling: config keys,
service names, effect keys. Declaration alone confers nothing — every seam
checks the descriptor first and the host grant second:

- configuration: `ExtensionConfigView` refuses undeclared keys everywhere,
  including `get()`, so an undeclared key reveals not even its presence;
  values are snapshotted at context build and copies are detached;
- services: `context.service(name)` returns the instance only when the name is
  declared *and* the host granted it; both refusals are the same typed error;
- effects: `context.invoke_effect(effect_key, request)` dispatches only when
  the key is declared *and* the host routed it.

**3. Authority-sensitive operations cross the canonical governed seam only.**
The reference route (`GovernedEffectRoute`) composes a host-resolved `Binding`
with `GovernedInvocationExecutionService`, so every extension effect produces
a real canonical `Invocation` row with `run_id`/`node_run_id`/`attempt_id`
correlation and the policy plane's own audit events. Extensions never see a
resolver, executor, Binding store, or provider. Dispatching outside a physical
Attempt is refused: activation scopes carry no execution correlation to spend.

**4. Cancellation is a read-only view over the canonical fence.**
`ExtensionCancellation.of_current_task()` answers for the calling asyncio task
at the moment it is asked (the runtime's work task for the Attempt), reading
`Task.cancelling()` — the pending request the canonical
`AttemptExecutionService.cancel`/run-fence path creates. The view never
cancels anything and never swallows `CancelledError`; `wait()` yields before
reporting so a pending canonical delivery keeps precedence over the view's own
`ExtensionCancelled` error. Extensions that catch `CancelledError` to record
evidence re-raise it, exactly like the runtime's own executor contract.

**5. Progress and provenance are host-attributed canonical events.** The host
supplies an `EventStore`; progress reports and settled effects land as
canonical envelopes correlated to the invoking Attempt, with the extension
identity in the envelope's `provenance` field. The `Invocation` model is not
widened: extension attribution is provenance metadata on the event stream, not
a second identity on the effect row.

**6. The lifecycle is three hooks; failures are attributed, not hidden.**
`ExtensionLifecycle` is a structural protocol — `activate(context)`,
`invoke(context)`, `deactivate(context)` — driven by the host through
`ExtensionHost`, which wraps hook failures in `ExtensionHookError` naming
the extension identity and preserves the original cause. The host
(`ExtensionHost`) is a context factory and lifecycle driver only: it is not a
scheduler, run store, or execution authority, and hosts keep driving physical
work through `AttemptExecutionService`.

**7. No ambient access.** There is no module-level "current context" or
"current container" accessor in the extension module; an extension can only
use the context it was handed. The SDK's import path is `maistro.extensions`.
Its single static anchor is the runtime package (`maistro.runtime` imports it
with a documented reason): the contract is the runtime-facing SDK, and this
keeps it visible to the reachability ratchet as wired while leaving the
package root — which every `import maistro` executes — free of new imports, so no optional dependency (e.g. cryptography, required by the
capability credential plane) can become an import-time requirement of the
library as a whole.

## Acceptance Criteria

The five acceptance criteria of issue #950, stated as checkable claims. Each
is ticked and proven by the `@pytest.mark.ac("ADR-104/AC-N")` markers in the
two suites this ADR's `tests:` field names.

- [x] **AC-1**: the context an extension receives is the complete authority
  surface: exactly the documented seams (`descriptor`, `identity`, `scope`,
  `config`, `cancellation`, `progress`, `service()`, `invoke_effect()`,
  `report_progress()`), a `__slots__` object with no `__dict__`, carrying no
  store, session, container, or connection handle, and exposing canonical
  Workspace/Agent/Run/NodeRun/Attempt identifiers only.
- [x] **AC-2**: the lifecycle is three hooks that receive only the public
  context; activation/deactivation run only on a context outside any Attempt
  and invocation only inside one — the exported drivers refuse a mismatched
  pair before any hook code runs — and a raising hook is attributed to the
  extension identity with the original cause preserved.
- [x] **AC-3**: authority is declared, then granted, and both halves are
  required: the host drops undeclared configuration values and undeclared
  service grants at composition so they never reach context storage, and the
  accessors refuse undeclared names (configuration refuses even the key's
  presence).
- [x] **AC-4**: authority-sensitive operations cross the canonical governed
  seam only: a declared, routed effect produces a real canonical `Invocation`
  row with run/node-run/attempt correlation through the
  `Capability → Provider → Binding → Invocation` path; undeclared, routeless,
  outside-Attempt, and cross-workspace dispatch are refused; cancellation is a
  read-only view over the canonical Attempt fence, and provenance lands in the
  canonical event envelope with the extension identity.
- [x] **AC-5**: the public interface contracts have conformance tests
  independent of any one extension implementation: the conformance suite's
  lifecycles are throwaways defined in the test file, and it binds no module
  outside the public SDK (`maistro.extensions`).

## Alternatives considered

- *Widen `Invocation` with extension metadata columns.* Rejected: it changes
  the persisted payload of every canonical effect row and couples the
  capabilities plane to extension identity; the envelope already has a typed
  provenance field for exactly this.
- *Ambient context (contextvars) so extension functions need no parameter.*
  Rejected: ambient access is the defect the issue names; an extension function
  that can fetch "the context" from anywhere can also fetch it outside the
  scope the host authorized.
- *Capability objects (opaque tokens per authority) instead of a descriptor.*
  Deferred to later M9 work if extension families outgrow descriptor strings;
  the seams here accept either refinement without breaking the context shape.

## Consequences

- The public context surface is a conformance-pinned contract; adding to it is
  an explicit, reviewed act (the surface test fails otherwise).
- The host seam treats the governed capability authorities as annotation-only
  (TYPE_CHECKING) and duck-typed at runtime: any eager `maistro.capabilities`
  import would drag the credential plane — and its cryptography dependency —
  into the SDK's import chain, defeating the auth module's fail-closed
  degradation. Host composition code imports the real types itself.
- Extension SDK work that follows — versioned SDK package and manifest schema
  (#949), public-SDK-only import enforcement (#951) — builds on these
  interfaces; the manifest's declared capabilities map onto
  `ExtensionDescriptor`.
- Graph/runtime wiring that hosts extension nodes as NodeRuns lands in later
  M9 work; until then the runtime package is the contract's static anchor and
  the reference-execution suite exercises it through the canonical Attempt
  path.
- New public SDK methods that only external code calls are referenced in
  `packages/maistro-core/src/_vulture_whitelist.py` (the same
  "contract ships first by design" posture as CampaignSelector and the
  learning lifecycle), so no per-identity ledger rows are added.

## See also

- #950 (this decision), #938 (epic), #949 (SDK package/manifest), #951
  (import enforcement).
- `docs/architecture/INTEROP-ONTOLOGY-v1.md` — canonical identities the
  context exposes (Workspace/Agent/Run/NodeRun/Attempt/Invocation).

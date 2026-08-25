---
id: ADR-069
title: "Code Registry — versioned, signed, microVM-isolated execution of substrate code refs"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate:
  - maistro-engine#ADR-053
  - maistro-engine#ADR-054
  - maistro-engine#ADR-068
implements: []
related:
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-056
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Implemented
---

# ADR-069: Code Registry

> **Convergence note (2026-08-19).** This ADR is marked `Implemented`, but the
> code implementing it has no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). That
> is not an oversight:
> [SPEC-257](../specs/SPEC-257-code-registry-resolve-core.md) scoped only the
> pure, testable core — the entry model, signature verification and
> `resolve()` contract — and put the microVM execution harness,
> Sentinel/Warden routing and resource caps in Non-goals, because they need a
> real microVM runtime plus ADR-054 sandbox tiers and ADR-068 authorization,
> none of which exist yet. The registry is reachable-by-design only from the
> `invoke()` that was never built.
>
> The status is knowingly left unchanged rather than corrected. The capability
> is still wanted, so `Deprecated` would be false; `Superseded` requires a
> `superseded-by` and nothing replaces this. Both are terminal, so choosing
> wrong forecloses the other, and ADR-097's forward-only lifecycle offers no
> transition back from `Implemented` for an ADR marked so optimistically.
> Correcting it truthfully needs either the missing substrate or a lifecycle
> that can express "specified, partially built, blocked".


**Status:** Proposed
**Date:** 2026-05-30
**Resolves:** the dangling "code registry" abstraction referenced by ADR-050, ADR-051,
ADR-053, and ADR-056 but never defined (owner, storage, ref resolution, or the security of
**executing** registered code).

---

## Context

Four ADRs lean on a "code registry" that resolves and **runs** code by `name@version`:

- **ADR-050** — `compensator`, `impact_estimator`, `idempotency_key` are "code-registry refs."
- **ADR-051** — escalation weights come from running an `impact_estimator`.
- **ADR-053** — `merge: ref` overlay fields and dynamic gates are `name@version` refs; sketches a
  `CodeRegistry` protocol (`resolve(ref) -> Callable`, `compatible(base, overlay) -> bool`).
- **ADR-056** — crash recovery asserts "code-registry versions still present and compatible."

None defines the registry. The unspecified part that matters most: these refs are **executable
code** invoked at tool-call time and at crash-recovery time. Running them is a code-execution
surface — the exact thing prompt-injection and supply-chain attacks target. A registry that
resolves a ref and calls it in-process is an RCE primitive. This ADR defines the registry and,
centrally, **how registered code is isolated when it runs**.

## Decision

### Ownership & shape

The code registry is **core** (maistro-core ships the registry, the protocol, and the execution
harness). A registry entry is content-addressed and versioned:

```python
class CodeKind(StrEnum):
    COMPENSATOR = "compensator"; IMPACT_ESTIMATOR = "impact_estimator"
    IDEMPOTENCY_KEY = "idempotency_key"; MERGE_RESOLVER = "merge_resolver"; DYNAMIC_GATE = "dynamic_gate"

class CodeEntry(BaseModel):
    name: str
    version: str                 # semver; refs are "name@version" (ADR-053 — unversioned refs refused)
    kind: CodeKind
    code_sha256: str             # content address of the body
    signature: bytes             # signed by admin or the registry key (ADR-028 pattern)
    trusted: bool = False        # engine-authored/shipped code may be trusted; everything else is not
```

### Resolution (ADR-053 contract, made concrete)

```python
class CodeRegistry(Protocol):
    def resolve(self, ref: str) -> CodeEntry: ...                  # "name@version" -> entry; raises CodeRefUnresolved
    def compatible(self, base_ref: str, overlay_ref: str) -> bool: ...  # semver: v2.x accepts v2.y; major bump = explicit
    async def invoke(self, ref: str, payload: CodePayload, ctx: ExecContext) -> CodeResult: ...
```

- Unversioned refs are **refused at recipe load** (ADR-053). A missing/incompatible ref **fails
  closed** with `CodeRefUnresolved` — never silently skipped (a skipped compensator = silent data
  loss; a skipped gate = silent bypass).
- Signature is verified on load; the registry **refuses to load an unsigned or invalid-signature
  entry** (mirrors ADR-028's `users.toml` rule). Major-version bumps require an explicit recipe
  update (ADR-053), never auto-upgrade.

### Execution isolation — the security core (microVM, fail-closed)

Registered code is **untrusted by default** and executes inside a **Hyperlight microVM** —
hardware-virtualized, per-invocation ephemeral, no host filesystem or network unless explicitly
granted. This is the same isolation surface the hive-conductor `hyperlight_executor` already
provides for graph nodes; the registry reuses it.

- **Fail-closed.** If no microVM runtime is available, an **untrusted** ref is **refused**
  (`isolation: "refused"`), *not* run as an unconfined host subprocess. Honest labelling: the
  result records the actual isolation achieved (`hyperlight` | `firecracker` | `refused` |
  `subprocess-unconfined`), never a claim the runtime can't back. (This is the exact fail-closed
  contract pinned by the staged hive-conductor hardening: untrusted + no sandbox ⇒ refuse.)
- **Trusted** entries (`trusted=True`, engine-authored, signed by the engine key) may run in a
  lighter sandbox **tier** (ADR-054) — but the label still reflects reality.
- **Substitutable backend.** Hyperlight is the default; any microVM meeting the same contract
  (Firecracker, gVisor, a future runtime) is acceptable. The contract — not the product — is
  normative: per-call ephemeral, hardware/kernel isolation, no ambient host access, resource caps.
- **Resource caps** come from the ADR-054 sandbox tier (memory, CPU, wall-clock); a microVM that
  exceeds its budget is killed and the invocation treated as a failure.

### Authorization — registry code cannot escalate (ADR-068)

Every `invoke()` is a **tool-call boundary**, so it goes through the ADR-068 evaluation:
**Sentinel** classifies the ref's effect (ADR-050 reversibility) and applies the tier ladder +
approver matrix + RLPHD gate; **Warden** scans the `payload` (untrusted inputs) for the risk
signal. Registered code therefore **cannot** acquire privilege the calling principal lacks, cannot
bypass an approval gate, and cannot beat the budget veto — it runs *inside* the same authorization
envelope as any other tool call. A compensator/estimator is itself tagged with a reversibility
class (ADR-050: a compensator must be `internal`/`reversible`, never `irreversible`).

### Failure modes (all explicit)

| Situation | Behaviour |
|-----------|-----------|
| Ref unresolved / unversioned | `CodeRefUnresolved`, fail closed (recipe load or invoke) |
| Unsigned / bad signature | refuse to load |
| Untrusted ref + no microVM runtime | refuse (`isolation: "refused"`) |
| microVM OOM / timeout | kill, treat as invocation failure |
| Compensator raises | `CompensatorError` bubbles to the ADR-051 path ("compensator failed; what now?") |
| Incompatible version on resume (ADR-056) | fail closed; recovery prompt, never run a mismatched body |

## Acceptance criteria

- [ ] `resolve("name@version")` returns the entry; unversioned or missing ref raises
      `CodeRefUnresolved` (fail closed) — never returns `None` silently.
- [ ] Registry refuses to load an unsigned / invalid-signature entry.
- [ ] An **untrusted** entry executes in a microVM; with no microVM runtime available it is
      **refused** (`isolation == "refused"`), never run as an unconfined host subprocess.
- [ ] The result's `isolation` field reflects the isolation actually achieved (no over-claim).
- [ ] `invoke()` routes through Sentinel (ADR-068): a ref whose effect exceeds the calling
      principal's authority raises the tier gate; Warden risk-scans the payload.
- [ ] Resource caps from the ADR-054 sandbox tier are enforced; over-budget microVM is killed.
- [ ] `compatible()` is semver: `v2.x` accepts `v2.y` overlays; a major bump requires an explicit
      recipe update.
- [ ] On ADR-056 resume, a version-incompatible ref fails closed rather than executing a
      mismatched body.

## Consequences

- ADR-050/051/053/056 gain a real referent: "code-registry ref" now means *a signed, versioned
  CodeEntry executed in a microVM under the ADR-068 envelope*.
- The engine grows a `code_registry/` module + the execution harness; Hyperlight (or an equivalent
  microVM) becomes a runtime dependency for executing untrusted refs. Without it, the engine still
  runs — untrusted refs are simply refused (degraded, fail-closed), and only `trusted` engine code
  executes.
- ADR-050's open question 1 ("single code registry shared with recipe-overlay refs, ADR-053?") is
  answered **yes** — one registry for compensators, impact estimators, merge resolvers, dynamic
  gates.

## Out of scope

- The bodies of specific compensators / estimators (consumer-authored).
- The microVM runtime's own packaging/build (Hyperlight is a dependency, not specified here).
- Cross-tenant registry trust / sharing — Stronghold concern (ADR-019).
- A marketplace / distribution channel for registry entries (separate ADR if needed).
